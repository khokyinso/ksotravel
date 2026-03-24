"""Agent 6.5: Visual QA

Analyzes rendered video frames with Claude Sonnet 4.6 vision to assess
visual quality before Telegram approval. Extracts keyframes via ffmpeg,
sends them to Sonnet for scoring on text readability, pacing, format
consistency, hook visibility, and CTA placement.

Model: Claude Sonnet 4.6 (vision)
Schedule: After Agent 7 (Video Builder), before Agent 8 (Telegram Gate)
Output: data/visual_qa_{date}.json
"""

import asyncio
import base64
import json
import os
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from utils import supabase_client as db

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

# What percentage of videos to spot-check (0.0 to 1.0)
SPOT_CHECK_RATIO = float(os.getenv("VISUAL_QA_SPOT_CHECK_RATIO", "0.25"))

# Minimum score to pass (1-10 scale)
MIN_PASS_SCORE = int(os.getenv("VISUAL_QA_MIN_SCORE", "6"))

# Number of frames to extract per video
FRAMES_PER_VIDEO = int(os.getenv("VISUAL_QA_FRAMES", "10"))

VISUAL_QA_SYSTEM_PROMPT = """You are the Visual Quality Analyst for @insearchofkso travel channels.
You receive keyframes extracted from a rendered TikTok/Reels video (30-60 seconds).
The frames are evenly spaced throughout the video timeline.

Your job is to evaluate the VISUAL QUALITY of the video for short-form social media.

SCORING CRITERIA (each 1-10):

1. HOOK VISIBILITY (Frame 1-2):
   - Is there text visible in the first 1-2 frames?
   - Is the hook text large, clear, and readable?
   - Does it grab attention immediately?
   - Would a viewer stop scrolling?

2. TEXT READABILITY (All frames):
   - Is text overlay legible against the background?
   - Is font size appropriate for mobile viewing?
   - Is there sufficient contrast between text and background?
   - Are text animations/transitions smooth?

3. VISUAL CONSISTENCY:
   - Is the color palette consistent across frames?
   - Do transitions feel smooth (no jarring jumps)?
   - Is the overall aesthetic cohesive?
   - Does it look professional, not amateurish?

4. FORMAT COMPLIANCE:
   - Does the video match its intended format (green_screen_text, pov_walking, etc.)?
   - Is it properly formatted for vertical (9:16) viewing?
   - Are there any blank/black frames?
   - Is content filling the frame appropriately?

5. CTA PLACEMENT (Last 2-3 frames):
   - Is the call-to-action visible in the final frames?
   - Is the trigger phrase readable?
   - Is the KSOTRAVEL promo code visible?
   - Does the ending feel intentional, not abrupt?

VERDICT RULES:
- Score 7-10: PASS — video is ready for Telegram review
- Score 5-6: WARN — video has issues but may be acceptable
- Score 1-4: REJECT — video needs re-rendering

Return ONLY JSON:
{
  "brief_id": "string",
  "overall_score": number (1-10),
  "hook_visibility": number (1-10),
  "text_readability": number (1-10),
  "visual_consistency": number (1-10),
  "format_compliance": number (1-10),
  "cta_placement": number (1-10),
  "verdict": "PASS" or "WARN" or "REJECT",
  "issues": ["list of specific issues found"],
  "notes": "brief summary of visual quality"
}"""


def _extract_frames(video_path: str, num_frames: int = 10) -> list[str]:
    """Extract evenly-spaced frames from a video using ffmpeg.

    Returns list of base64-encoded PNG images.
    """
    frames = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Get video duration first
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        try:
            result = subprocess.run(
                probe_cmd, capture_output=True, text=True, timeout=30
            )
            duration = float(result.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not probe video duration: {e}, using 30s default")
            duration = 30.0

        # Calculate frame extraction interval
        interval = duration / (num_frames + 1)

        # Extract frames with ffmpeg
        for i in range(num_frames):
            timestamp = interval * (i + 1)
            output_path = os.path.join(tmpdir, f"frame_{i:03d}.png")

            extract_cmd = [
                "ffmpeg", "-y", "-ss", f"{timestamp:.2f}",
                "-i", video_path,
                "-vframes", "1",
                "-vf", "scale=540:-1",  # Scale down for token efficiency
                output_path,
            ]
            try:
                subprocess.run(
                    extract_cmd, capture_output=True, timeout=30,
                    check=True,
                )
            except Exception as e:
                logger.debug(f"Frame extraction failed at {timestamp:.1f}s: {e}")
                continue

            if os.path.exists(output_path):
                with open(output_path, "rb") as f:
                    b64 = base64.standard_b64encode(f.read()).decode("utf-8")
                    frames.append(b64)

    logger.debug(f"Extracted {len(frames)} frames from {video_path}")
    return frames


async def _download_video(video_url: str, dest_path: str) -> bool:
    """Download a rendered video from URL (Supabase Storage or Railway)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                f.write(resp.content)
        return True
    except Exception as e:
        logger.error(f"Failed to download video from {video_url}: {e}")
        return False


async def _analyze_video_frames(
    brief_id: str,
    frames: list[str],
    video_format: str,
    destination: str,
) -> dict:
    """Send frames to Claude Sonnet 4.6 vision for visual quality analysis."""
    from utils.token_tracker import tracked_create

    # Build image content blocks
    content: list[dict] = [
        {
            "type": "text",
            "text": (
                f"Analyze these {len(frames)} keyframes from a rendered TikTok/Reels video.\n"
                f"Brief ID: {brief_id}\n"
                f"Destination: {destination}\n"
                f"Intended format: {video_format}\n"
                f"Frames are in chronological order (first frame = video start, last frame = video end)."
            ),
        }
    ]

    for i, b64_frame in enumerate(frames):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64_frame,
            },
        })
        content.append({
            "type": "text",
            "text": f"Frame {i + 1}/{len(frames)}",
        })

    text, _usage = tracked_create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=[{
            "type": "text",
            "text": VISUAL_QA_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": content}],
        agent_name="visual_qa",
        context={"brief_id": brief_id, "destination": destination},
    )

    # Parse JSON response
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse visual QA response for {brief_id}: {e}")
        result = {
            "brief_id": brief_id,
            "overall_score": 0,
            "verdict": "REJECT",
            "issues": [f"Parse error: {e}"],
            "notes": "Could not parse AI response",
        }

    result["brief_id"] = brief_id
    return result


async def analyze_video(
    brief_id: str,
    video_url: str,
    video_format: str = "green_screen_text",
    destination: str = "",
) -> dict:
    """Full pipeline: download → extract frames → analyze with Sonnet.

    Returns visual QA result dict.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, f"{brief_id}.mp4")

        # Download
        success = await _download_video(video_url, video_path)
        if not success:
            return {
                "brief_id": brief_id,
                "overall_score": 0,
                "verdict": "REJECT",
                "issues": ["Failed to download video"],
                "notes": "Video download failed",
            }

        # Extract frames
        frames = _extract_frames(video_path, num_frames=FRAMES_PER_VIDEO)
        if not frames:
            return {
                "brief_id": brief_id,
                "overall_score": 0,
                "verdict": "REJECT",
                "issues": ["No frames extracted"],
                "notes": "Frame extraction failed — video may be corrupted",
            }

        # Analyze with Sonnet vision
        result = await _analyze_video_frames(
            brief_id, frames, video_format, destination
        )
        return result


async def run(run_date: date | None = None) -> dict:
    """Run Visual QA on rendered videos.

    Spot-checks a percentage of videos (configurable via VISUAL_QA_SPOT_CHECK_RATIO).
    Videos scoring below MIN_PASS_SCORE are flagged for re-rendering.

    Returns:
        dict with "results" (list) and "stats" (summary).
    """
    if run_date is None:
        run_date = date.today()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check
    cache_file = DATA_DIR / f"visual_qa_{run_date.isoformat()}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("results"):
            logger.info(
                f"=== Visual QA CACHED for {run_date}: "
                f"{len(cached['results'])} videos analyzed ==="
            )
            return cached

    logger.info(f"=== Visual QA starting for {run_date} ===")

    # Load rendered videos
    videos_file = DATA_DIR / f"videos_{run_date.isoformat()}.json"
    if not videos_file.exists():
        logger.error(f"No videos file found: {videos_file}")
        return {"results": [], "stats": {"error": "No videos file"}}

    with open(videos_file) as f:
        videos_data = json.load(f)

    videos = videos_data.get("videos", {})
    if not videos:
        logger.warning("No rendered videos to analyze")
        return {"results": [], "stats": {"total": 0}}

    # Load briefs for enrichment (video_format, destination)
    briefs_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
    briefs_map = {}
    if briefs_file.exists():
        with open(briefs_file) as f:
            briefs_data = json.load(f)
        briefs_map = {
            b["brief_id"]: b
            for b in briefs_data.get("briefs", [])
            if "brief_id" in b
        }

    # Select videos to spot-check
    import random
    all_brief_ids = list(videos.keys())
    sample_size = max(1, int(len(all_brief_ids) * SPOT_CHECK_RATIO))
    sample_ids = random.sample(all_brief_ids, min(sample_size, len(all_brief_ids)))

    logger.info(
        f"Spot-checking {len(sample_ids)}/{len(all_brief_ids)} videos "
        f"({SPOT_CHECK_RATIO:.0%} ratio)"
    )

    # Analyze videos concurrently (limit concurrency to avoid memory issues)
    semaphore = asyncio.Semaphore(3)
    all_results = []

    async def analyze_with_limit(brief_id: str) -> dict:
        async with semaphore:
            video_data = videos[brief_id]
            video_url = video_data.get("url", "")
            brief = briefs_map.get(brief_id, {})
            video_format = brief.get("video_format", "green_screen_text")
            destination = brief.get("destination", brief_id.split("_")[0])

            logger.info(f"Analyzing {brief_id} ({destination}, {video_format})...")
            result = await analyze_video(
                brief_id, video_url, video_format, destination
            )

            verdict = result.get("verdict", "REJECT")
            score = result.get("overall_score", 0)
            if verdict == "PASS":
                logger.info(f"PASS: {brief_id} (score: {score}/10)")
            elif verdict == "WARN":
                logger.warning(f"WARN: {brief_id} (score: {score}/10) — {result.get('notes', '')[:80]}")
            else:
                logger.error(f"REJECT: {brief_id} (score: {score}/10) — {result.get('issues', [])}")

            return result

    tasks = [analyze_with_limit(bid) for bid in sample_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for bid, result in zip(sample_ids, results):
        if isinstance(result, Exception):
            logger.error(f"Visual QA failed for {bid}: {result}")
            all_results.append({
                "brief_id": bid,
                "overall_score": 0,
                "verdict": "REJECT",
                "issues": [f"Analysis error: {result}"],
                "notes": "Visual QA encountered an error",
            })
        else:
            all_results.append(result)

    # Calculate stats
    passed = [r for r in all_results if r.get("verdict") == "PASS"]
    warned = [r for r in all_results if r.get("verdict") == "WARN"]
    rejected = [r for r in all_results if r.get("verdict") == "REJECT"]

    avg_score = (
        sum(r.get("overall_score", 0) for r in all_results) / len(all_results)
        if all_results else 0
    )

    # Collect rejected brief_ids for potential re-rendering
    rejected_ids = [r["brief_id"] for r in rejected]

    stats = {
        "total_videos": len(all_brief_ids),
        "spot_checked": len(sample_ids),
        "passed": len(passed),
        "warned": len(warned),
        "rejected": len(rejected),
        "average_score": round(avg_score, 1),
        "rejected_brief_ids": rejected_ids,
        "pass_rate": f"{len(passed) / len(all_results) * 100:.1f}%" if all_results else "0%",
    }

    # Save results
    output = {
        "date": run_date.isoformat(),
        "spot_check_ratio": SPOT_CHECK_RATIO,
        "min_pass_score": MIN_PASS_SCORE,
        "frames_per_video": FRAMES_PER_VIDEO,
        "results": all_results,
        "stats": stats,
    }

    with open(cache_file, "w") as f:
        json.dump(output, f, indent=2)
    logger.info(f"Saved visual QA results to {cache_file}")

    # Save to Supabase
    try:
        db.save_visual_qa_results(all_results, run_date)
    except Exception as e:
        logger.warning(f"Failed to save visual QA results to Supabase: {e}")

    logger.info(
        f"=== Visual QA complete: {len(passed)} PASS, {len(warned)} WARN, "
        f"{len(rejected)} REJECT (avg score: {avg_score:.1f}/10) ==="
    )

    return output


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result.get("stats", {}), indent=2))
