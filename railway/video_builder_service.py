"""Railway Video Builder Service — Agent 7 Cloud Backend

FastAPI service that renders TikTok/Reels videos from script data.
Fetches background footage from Pexels, composites text overlays
using Pillow + moviepy, uploads MP4s to Supabase Storage.

Deploy: Railway (Docker)
Endpoint: POST /render
"""

import asyncio
import hashlib
import io
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel

load_dotenv(override=True)

app = FastAPI(title="KSO Video Builder", version="1.0.0")

# Concurrency limit for rendering
RENDER_SEMAPHORE = asyncio.Semaphore(2)  # Low concurrency to avoid OOM on Railway

# Video specs
WIDTH = 1080
HEIGHT = 1920
FPS = 24
FONT_SIZE = 52
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# Fallback for local testing (macOS)
FONT_PATH_LOCAL = "/System/Library/Fonts/Helvetica.ttc"
TEXT_Y_START = 1200  # Start text in bottom third
LINE_SPACING = 80
FADE_STAGGER = 0.3  # seconds between line appearances
SHADOW_OFFSET = 2

# Brand colors per destination
BRAND_COLORS = {
    "japan": "#E8272A", "greece": "#0D5EAF", "italy": "#009246",
    "korea": "#00A693", "thailand": "#FFB400", "mexico": "#006847",
    "portugal": "#006600", "spain": "#AA151B", "france": "#002395",
    "turkey": "#E30A17", "poland": "#DC143C", "china": "#DE2910",
}

# Pexels search tags per destination
FOOTAGE_TAGS = {
    "japan": "tokyo street, cherry blossom japan, japanese temple",
    "greece": "santorini, greek island, athens acropolis",
    "italy": "rome colosseum, venice canal, amalfi coast",
    "korea": "seoul neon, korean temple, jeju island",
    "thailand": "bangkok temple, thai beach, street food thailand",
    "mexico": "mexico city, tulum ruins, cenote",
    "portugal": "lisbon tram, porto bridge, algarve coast",
    "spain": "barcelona gaudi, madrid plaza, seville",
    "france": "paris eiffel, provence lavender, nice coast",
    "turkey": "istanbul mosque, cappadocia balloon, turkish bazaar",
    "poland": "krakow square, warsaw old town, gdansk",
    "china": "shanghai skyline, great wall, beijing temple",
}

# Cache for downloaded footage
_footage_cache: dict[str, str] = {}


# ── Models ───────────────────────────────────────────────────────────────


class ScriptPayload(BaseModel):
    brief_id: str
    destination: str
    script_lines: list[str]
    target_length_seconds: int = 30
    comment_trigger_phrase: str = ""
    video_format: str = "green_screen_text"


class RenderRequest(BaseModel):
    scripts: list[ScriptPayload]
    date: str


class VideoResult(BaseModel):
    url: str
    duration: int


# ── Pexels ───────────────────────────────────────────────────────────────


async def fetch_pexels_footage(
    destination: str, duration_hint: int, tmp_dir: str
) -> str | None:
    """Fetch portrait video from Pexels for a destination. Returns local path."""
    import sys

    class _Log:
        def info(self, msg): print(f"[PEXELS] {msg}", flush=True)
        def warning(self, msg): print(f"[PEXELS] WARN: {msg}", flush=True)
        def error(self, msg): print(f"[PEXELS] ERROR: {msg}", flush=True)
    log = _Log()

    # Check cache
    cache_key = destination
    if cache_key in _footage_cache and Path(_footage_cache[cache_key]).exists():
        log.info(f"[{destination}] Using cached footage")
        return _footage_cache[cache_key]

    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        log.error(f"[{destination}] PEXELS_API_KEY not set")
        return None

    tags = FOOTAGE_TAGS.get(destination, f"{destination} travel")
    query = tags.split(",")[0].strip()
    log.info(f"[{destination}] Searching Pexels for: '{query}'")

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                "https://api.pexels.com/videos/search",
                params={
                    "query": query,
                    "per_page": 5,
                    "orientation": "portrait",
                    "size": "medium",
                },
                headers={"Authorization": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            log.info(f"[{destination}] Pexels API returned {len(data.get('videos', []))} videos")
        except Exception as e:
            log.error(f"[{destination}] Pexels API search failed: {e}")
            return None

    videos = data.get("videos", [])
    if not videos:
        log.warning(f"[{destination}] No videos found for '{query}'")
        return None

    import random
    random.shuffle(videos)

    for i, video in enumerate(videos):
        files = video.get("video_files", [])
        log.info(f"[{destination}] Video {i+1}: {len(files)} files available")
        for f in files:
            log.info(f"  {f.get('width')}x{f.get('height')} quality={f.get('quality')}")

        # Use SD quality for faster download + encode
        sd_files = [
            f for f in files
            if 720 <= f.get("height", 0) <= 1080 and f.get("width", 0) <= f.get("height", 0)
        ]
        if not sd_files:
            sd_files = [f for f in files if f.get("height", 0) >= 480]
        if not sd_files:
            sd_files = files

        if not sd_files:
            log.warning(f"[{destination}] Video {i+1}: no suitable files after filtering")
            continue

        chosen = sd_files[0]
        download_url = chosen.get("link")
        if not download_url:
            log.warning(f"[{destination}] Video {i+1}: no download link")
            continue

        log.info(f"[{destination}] Downloading {chosen.get('width')}x{chosen.get('height')} from {download_url[:80]}...")

        footage_path = os.path.join(tmp_dir, f"{destination}_footage.mp4")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as dl_client:
                async with dl_client.stream("GET", download_url) as dl_resp:
                    dl_resp.raise_for_status()
                    total = 0
                    with open(footage_path, "wb") as f:
                        async for chunk in dl_resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            total += len(chunk)
            file_size_mb = total / (1024 * 1024)
            log.info(f"[{destination}] Downloaded {file_size_mb:.1f} MB to {footage_path}")
            _footage_cache[cache_key] = footage_path
            return footage_path
        except Exception as e:
            log.error(f"[{destination}] Download failed: {e}")
            continue

    log.error(f"[{destination}] All video download attempts failed")
    return None


# ── Text Rendering (Pillow) ──────────────────────────────────────────────


def _get_font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    """Get font, with fallback for local testing."""
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except OSError:
        try:
            return ImageFont.truetype(FONT_PATH_LOCAL, size)
        except OSError:
            return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def render_text_frame(
    lines: list[str],
    visible_count: int,
    trigger_phrase: str,
    brand_color: str,
    width: int = WIDTH,
    height: int = HEIGHT,
) -> Image.Image:
    """Render text overlay as a transparent RGBA image.

    Only shows the first `visible_count` lines (for fade-in stagger).
    """
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _get_font(FONT_SIZE)
    small_font = _get_font(FONT_SIZE - 8)

    y = TEXT_Y_START
    for i, line in enumerate(lines[:visible_count]):
        text = line.strip()
        if not text:
            continue

        # Get text bounding box for centering
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        x = (width - text_w) // 2

        # Check if this is the CTA line (contains trigger phrase)
        is_cta = trigger_phrase and trigger_phrase.lower() in text.lower()

        if is_cta:
            # Draw colored background box
            color_rgb = _hex_to_rgb(brand_color)
            pad = 20
            box_rect = [x - pad, y - pad // 2, x + text_w + pad, y + FONT_SIZE + pad]
            draw.rounded_rectangle(box_rect, radius=12, fill=(*color_rgb, 220))
            # White text on colored box
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
        else:
            # Shadow
            draw.text(
                (x + SHADOW_OFFSET, y + SHADOW_OFFSET),
                text,
                font=font,
                fill=(0, 0, 0, 180),
            )
            # White text
            draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

        y += LINE_SPACING

    return img


# ── Video Composition ────────────────────────────────────────────────────


def compose_video(
    script: ScriptPayload,
    footage_path: str | None,
    output_path: str,
) -> bool:
    """Compose a single video from script + footage. Returns True on success."""
    try:
        from moviepy.editor import (
            ColorClip, CompositeVideoClip, ImageClip, VideoFileClip,
        )
    except ImportError:
        from moviepy import (
            ColorClip, CompositeVideoClip, ImageClip, VideoFileClip,
        )

    duration = script.target_length_seconds
    brand_color = BRAND_COLORS.get(script.destination, "#FFFFFF")
    lines = script.script_lines
    num_lines = len(lines)

    # Background: footage or solid color
    if footage_path and Path(footage_path).exists():
        try:
            bg = VideoFileClip(footage_path).resize((WIDTH, HEIGHT))
            if bg.duration < duration:
                bg = bg.loop(duration=duration)
            else:
                bg = bg.subclip(0, duration)
        except Exception:
            bg = ColorClip(size=(WIDTH, HEIGHT), color=(20, 20, 30)).set_duration(duration)
    else:
        bg = ColorClip(size=(WIDTH, HEIGHT), color=(20, 20, 30)).set_duration(duration)

    # Create text overlay clips with fade-in stagger
    text_clips = []
    for visible_count in range(1, num_lines + 1):
        start_time = (visible_count - 1) * FADE_STAGGER
        # Duration: until next line appears, or until end
        if visible_count < num_lines:
            clip_duration = duration - start_time
        else:
            clip_duration = duration - start_time

        if clip_duration <= 0:
            continue

        frame = render_text_frame(
            lines, visible_count, script.comment_trigger_phrase, brand_color
        )
        frame_array = __import__("numpy").array(frame)

        clip = (
            ImageClip(frame_array, ismask=False, transparent=True)
            .set_duration(clip_duration)
            .set_start(start_time)
            .set_position((0, 0))
        )
        text_clips.append(clip)

    # Composite
    final = CompositeVideoClip([bg] + text_clips, size=(WIDTH, HEIGHT))
    final = final.set_duration(duration)

    # Write
    final.write_videofile(
        output_path,
        fps=FPS,
        codec="libx264",
        audio=False,  # No music for MVP
        preset="ultrafast",
        threads=2,
        logger=None,
    )

    # Cleanup moviepy resources
    final.close()
    bg.close()
    for c in text_clips:
        c.close()

    return True


# ── Supabase Upload ──────────────────────────────────────────────────────


async def upload_to_supabase(file_path: str, brief_id: str, run_date: str) -> str | None:
    """Upload MP4 to Supabase Storage. Returns public URL."""
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None

    sb = create_client(url, key)
    storage_path = f"{run_date}/{brief_id}.mp4"

    try:
        with open(file_path, "rb") as f:
            sb.storage.from_("videos").upload(
                storage_path, f.read(), {"content-type": "video/mp4"}
            )
        public_url = sb.storage.from_("videos").get_public_url(storage_path)
        return public_url
    except Exception as e:
        # If bucket doesn't exist, try creating it
        if "not found" in str(e).lower() or "Bucket" in str(e):
            try:
                sb.storage.create_bucket("videos", {"public": True})
                with open(file_path, "rb") as f:
                    sb.storage.from_("videos").upload(
                        storage_path, f.read(), {"content-type": "video/mp4"}
                    )
                return sb.storage.from_("videos").get_public_url(storage_path)
            except Exception:
                pass
        return None


# ── Render Single ────────────────────────────────────────────────────────


async def render_single(
    script: ScriptPayload, tmp_dir: str, run_date: str
) -> dict:
    """Render a single video. Returns result dict."""
    async with RENDER_SEMAPHORE:
        try:
            # Fetch footage
            print(f"[RENDER] {script.brief_id}: fetching footage...", flush=True)
            footage_path = await fetch_pexels_footage(
                script.destination, script.target_length_seconds, tmp_dir
            )
            print(f"[RENDER] {script.brief_id}: footage={'OK: ' + str(footage_path) if footage_path else 'NONE (black bg)'}", flush=True)

            # Compose video
            print(f"[RENDER] {script.brief_id}: composing video ({script.target_length_seconds}s, {len(script.script_lines)} lines)...", flush=True)
            output_path = os.path.join(tmp_dir, f"{script.brief_id}.mp4")
            success = await asyncio.to_thread(
                compose_video, script, footage_path, output_path
            )
            print(f"[RENDER] {script.brief_id}: compose={'OK' if success else 'FAILED'}", flush=True)

            if not success:
                return {"brief_id": script.brief_id, "error": "Composition failed"}

            # Upload to Supabase
            video_url = await upload_to_supabase(output_path, script.brief_id, run_date)
            if not video_url:
                return {"brief_id": script.brief_id, "error": "Upload failed"}

            # Get file size
            file_size = os.path.getsize(output_path)

            return {
                "brief_id": script.brief_id,
                "url": video_url,
                "duration": script.target_length_seconds,
                "file_size_bytes": file_size,
            }

        except Exception as e:
            return {"brief_id": script.brief_id, "error": str(e)}


# ── Job Store ─────────────────────────────────────────────────────────────

import uuid

_jobs: dict[str, dict] = {}  # job_id -> {status, videos, errors, stats, tmp_dir}


async def _run_render_job(job_id: str, scripts: list[ScriptPayload], run_date: str):
    """Background task that renders all scripts for a job."""
    tmp_dir = tempfile.mkdtemp(prefix="kso_render_")
    _jobs[job_id]["tmp_dir"] = tmp_dir

    try:
        results = []
        for script in scripts:
            result = await render_single(script, tmp_dir, run_date)
            results.append(result)

        videos = {}
        errors = []
        for r in results:
            if "error" in r:
                errors.append(r)
            else:
                videos[r["brief_id"]] = {
                    "url": r["url"],
                    "duration": r["duration"],
                }

        _jobs[job_id].update({
            "status": "complete",
            "videos": videos,
            "errors": errors,
            "stats": {
                "total": len(scripts),
                "rendered": len(videos),
                "failed": len(errors),
            },
        })
    except Exception as e:
        _jobs[job_id].update({
            "status": "failed",
            "videos": {},
            "errors": [{"error": str(e)}],
            "stats": {"total": len(scripts), "rendered": 0, "failed": len(scripts)},
        })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Endpoints ────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/render/submit")
async def render_submit(request: RenderRequest):
    """Submit a render job. Returns immediately with a job_id to poll."""
    if not request.scripts:
        raise HTTPException(status_code=400, detail="No scripts provided")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {
        "status": "processing",
        "videos": {},
        "errors": [],
        "stats": {"total": len(request.scripts), "rendered": 0, "failed": 0},
    }

    asyncio.create_task(_run_render_job(job_id, request.scripts, request.date))

    return {"job_id": job_id, "status": "processing", "total": len(request.scripts)}


@app.get("/render/status/{job_id}")
async def render_status(job_id: str):
    """Poll for job status."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _jobs[job_id]


@app.post("/render")
async def render(request: RenderRequest):
    """Synchronous render (legacy). Kept for backwards compatibility."""
    if not request.scripts:
        raise HTTPException(status_code=400, detail="No scripts provided")

    tmp_dir = tempfile.mkdtemp(prefix="kso_render_")

    try:
        results = []
        for script in request.scripts:
            result = await render_single(script, tmp_dir, request.date)
            results.append(result)

        videos = {}
        errors = []
        for r in results:
            if "error" in r:
                errors.append(r)
            else:
                videos[r["brief_id"]] = {
                    "url": r["url"],
                    "duration": r["duration"],
                }

        return {
            "status": "complete",
            "videos": videos,
            "errors": errors,
            "stats": {
                "total": len(request.scripts),
                "rendered": len(videos),
                "failed": len(errors),
            },
        }

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
