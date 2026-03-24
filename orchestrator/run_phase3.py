"""Phase 3 Orchestrator — Video Rendering + Visual QA + Telegram Approval

Runs Agents 7, 6.5, 8:
  7.  Video Builder — renders PASS scripts to MP4 via Railway
  6.5 Visual QA — spot-checks rendered videos with Sonnet vision
  8.  Telegram Gate — sends samples for human approval

Output: Rendered, QA'd, and approved videos ready for publishing (Phase 4).

Usage:
    python -m orchestrator.run_phase3
    python -m orchestrator.run_phase3 --date 2026-03-23
    python -m orchestrator.run_phase3 --skip-telegram
    python -m orchestrator.run_phase3 --skip-visual-qa
"""

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from loguru import logger

DATA_DIR = Path(__file__).parent.parent / "data"


async def run_phase3(
    run_date: date,
    skip_telegram: bool = False,
    skip_visual_qa: bool = False,
) -> dict:
    """Run Phase 3 pipeline."""
    start_time = datetime.now()
    results = {}

    logger.info(f"{'='*60}")
    logger.info(f"PHASE 3 — Video Rendering + Visual QA + Approval — {run_date}")
    logger.info(f"{'='*60}")

    # Step 0: Validate Phase 2 outputs exist
    required_files = [
        DATA_DIR / f"scripts_{run_date.isoformat()}.json",
        DATA_DIR / f"audit_results_{run_date.isoformat()}.json",
    ]
    for f in required_files:
        if not f.exists():
            logger.error(f"Missing required Phase 2 output: {f.name}")
            logger.info("Run Phase 2 first: python -m orchestrator.run_phase2")
            return _finalize({"error": f"Missing {f.name}"}, run_date, start_time)

    # Step 1: Check Railway health
    logger.info("Step 1: Checking Railway service health...")
    from agents import video_builder
    is_healthy = await video_builder.check_railway_health()

    if not is_healthy:
        logger.error("Railway service is not available — cannot render videos")
        logger.info("Set RAILWAY_VIDEO_SERVICE_URL in .env and deploy the service")
        return _finalize({"error": "Railway service unavailable"}, run_date, start_time)

    # Step 2: Render videos
    logger.info("Step 2: Rendering videos via Railway...")
    render_result = await video_builder.build_videos(run_date)
    results["video_builder"] = render_result

    videos = render_result.get("videos", {})
    stats = render_result.get("stats", {})
    logger.info(
        f"Video Builder: {stats.get('rendered', 0)} rendered, "
        f"{stats.get('failed', 0)} failed"
    )

    if not videos:
        logger.warning("No videos rendered — skipping Visual QA and Telegram gate")
        return _finalize(results, run_date, start_time)

    # Step 3: Visual QA (spot-check rendered videos with Sonnet vision)
    if skip_visual_qa:
        logger.info("Step 3: Visual QA skipped (--skip-visual-qa flag)")
        results["visual_qa"] = {"skipped": True}
    else:
        logger.info("Step 3: Running Visual QA on rendered videos...")
        from agents import visual_qa
        vqa_result = await visual_qa.run(run_date)
        results["visual_qa"] = vqa_result

        vqa_stats = vqa_result.get("stats", {})
        logger.info(
            f"Visual QA: {vqa_stats.get('passed', 0)} PASS, "
            f"{vqa_stats.get('warned', 0)} WARN, "
            f"{vqa_stats.get('rejected', 0)} REJECT "
            f"(avg score: {vqa_stats.get('average_score', 'N/A')}/10)"
        )

        # Remove rejected videos from the pool before Telegram review
        rejected_ids = set(vqa_stats.get("rejected_brief_ids", []))
        if rejected_ids:
            logger.warning(f"Removing {len(rejected_ids)} visually rejected videos from pool")
            videos = {k: v for k, v in videos.items() if k not in rejected_ids}

            if not videos:
                logger.error("All videos rejected by Visual QA — nothing to approve")
                return _finalize(results, run_date, start_time)

    # Step 4: Select samples for Telegram
    logger.info("Step 4: Selecting samples for Telegram review...")

    # Load briefs for sample selection
    briefs_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
    briefs_map = {}
    sample_briefs = {}
    if briefs_file.exists():
        with open(briefs_file) as f:
            briefs_data = json.load(f)
        for b in briefs_data.get("briefs", []):
            bid = b.get("brief_id", "")
            briefs_map[bid] = b
            if b.get("is_sample_video"):
                sample_briefs[b.get("destination", "")] = bid

    # Pick 1 sample per destination (prefer is_sample_video, fallback to first rendered)
    sample_videos = {}
    dest_videos = {}
    for brief_id, video_data in videos.items():
        dest = brief_id.split("_")[0]
        if dest not in dest_videos:
            dest_videos[dest] = []
        dest_videos[dest].append({"brief_id": brief_id, **video_data})

    for dest, vids in dest_videos.items():
        # Prefer the designated sample
        sample_bid = sample_briefs.get(dest)
        chosen = None
        if sample_bid:
            chosen = next((v for v in vids if v["brief_id"] == sample_bid), None)
        if not chosen:
            chosen = vids[0]  # First rendered video for this destination

        sample_videos[dest] = {
            "url": chosen["url"],
            "brief_id": chosen["brief_id"],
        }

    logger.info(f"Selected {len(sample_videos)} samples for review")

    # Step 5: Telegram approval gate
    if skip_telegram:
        logger.info("Step 5: Telegram skipped (--skip-telegram flag)")
        approval_result = {
            "approved": list(sample_videos.keys()),
            "rejected": [],
            "auto_approved": list(sample_videos.keys()),
        }
    else:
        logger.info("Step 5: Running Telegram review gate...")
        from agents import telegram_gate
        approval_result = await telegram_gate.run(
            sample_videos, briefs_map=briefs_map
        )

    results["telegram_gate"] = approval_result

    # Step 6: Update Supabase with approval status
    logger.info("Step 6: Updating approval status in Supabase...")
    from utils import supabase_client as db

    approved_count = 0
    rejected_count = 0

    for dest in approval_result.get("approved", []):
        try:
            count = db.approve_channel_videos(dest, run_date)
            approved_count += count
        except Exception as e:
            logger.error(f"Failed to approve {dest}: {e}")

    for dest in approval_result.get("rejected", []):
        try:
            count = db.reject_channel_videos(dest, run_date)
            rejected_count += count
        except Exception as e:
            logger.error(f"Failed to reject {dest}: {e}")

    results["approval_summary"] = {
        "videos_approved": approved_count,
        "videos_rejected": rejected_count,
        "channels_approved": len(approval_result.get("approved", [])),
        "channels_rejected": len(approval_result.get("rejected", [])),
    }

    return _finalize(results, run_date, start_time)


def _finalize(results: dict, run_date: date, start_time: datetime) -> dict:
    """Build summary and save."""
    elapsed = (datetime.now() - start_time).total_seconds()

    summary = {
        "date": run_date.isoformat(),
        "phase": "phase3",
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
    }

    summary_file = DATA_DIR / f"phase3_summary_{run_date.isoformat()}.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    render_stats = results.get("video_builder", {}).get("stats", {})
    approval = results.get("approval_summary", {})

    logger.info(f"{'='*60}")
    logger.info(f"PHASE 3 COMPLETE in {elapsed:.1f}s")
    logger.info(f"Videos rendered: {render_stats.get('rendered', 0)}")
    logger.info(f"Videos failed: {render_stats.get('failed', 0)}")
    logger.info(f"Channels approved: {approval.get('channels_approved', 'N/A')}")
    logger.info(f"Channels rejected: {approval.get('channels_rejected', 'N/A')}")
    logger.info(f"Summary: {summary_file}")
    logger.info(f"{'='*60}")

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Run Phase 3 — Video Rendering + Telegram Approval"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Run date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--skip-telegram",
        action="store_true",
        help="Skip Telegram approval gate (auto-approve all)",
    )
    parser.add_argument(
        "--skip-visual-qa",
        action="store_true",
        help="Skip Visual QA step (no Sonnet vision analysis)",
    )
    args = parser.parse_args()

    if args.date:
        run_date = date.fromisoformat(args.date)
    else:
        run_date = date.today()

    result = asyncio.run(run_phase3(
        run_date,
        skip_telegram=args.skip_telegram,
        skip_visual_qa=args.skip_visual_qa,
    ))

    has_errors = "error" in result.get("results", {})
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
