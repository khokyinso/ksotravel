"""Agent 7: Video Builder (Mac Stub)

Thin client that loads PASS scripts, enriches them with brief data,
sends render jobs to Railway cloud service, saves results to Supabase.

Model: None (no AI calls)
Schedule: 7:00 AM EST
Output: Rendered MP4 URLs in Supabase rendered_videos table
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv
from loguru import logger

from utils import supabase_client as db

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_pass_scripts(run_date: date) -> list[dict]:
    """Load scripts that passed audit."""
    # Load audit results
    audit_file = DATA_DIR / f"audit_results_{run_date.isoformat()}.json"
    if not audit_file.exists():
        logger.error(f"No audit results file: {audit_file}")
        return []
    with open(audit_file) as f:
        audit_data = json.load(f)

    pass_ids = {
        r["brief_id"]
        for r in audit_data.get("results", [])
        if r.get("verdict") == "PASS"
    }
    logger.info(f"Found {len(pass_ids)} PASS verdicts")

    # Load scripts
    scripts_file = DATA_DIR / f"scripts_{run_date.isoformat()}.json"
    if not scripts_file.exists():
        logger.error(f"No scripts file: {scripts_file}")
        return []
    with open(scripts_file) as f:
        scripts_data = json.load(f)

    pass_scripts = [
        s for s in scripts_data.get("scripts", [])
        if s.get("brief_id") in pass_ids
    ]
    logger.info(f"Matched {len(pass_scripts)} PASS scripts")

    # Load briefs for enrichment
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

    # Enrich scripts with brief data
    enriched = []
    for script in pass_scripts:
        bid = script.get("brief_id", "")
        brief = briefs_map.get(bid, {})
        enriched.append({
            "brief_id": bid,
            "destination": brief.get("destination", bid.split("_")[0]),
            "script_lines": script.get("script_lines", []),
            "target_length_seconds": script.get("target_length_seconds", 30),
            "comment_trigger_phrase": brief.get("comment_trigger_phrase", ""),
            "video_format": script.get("video_format", "green_screen_text"),
        })

    return enriched


async def check_railway_health() -> bool:
    """Check if Railway service is healthy. Retries with backoff."""
    service_url = os.getenv("RAILWAY_VIDEO_SERVICE_URL", "")
    if not service_url:
        logger.error("RAILWAY_VIDEO_SERVICE_URL not set")
        return False

    import asyncio
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{service_url}/health")
                if resp.status_code == 200:
                    logger.info("Railway service is healthy")
                    return True
        except Exception as e:
            logger.warning(f"Railway health check attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))

    return False


async def build_videos(run_date: date) -> dict:
    """Submit render job to Railway and save results.

    Returns: {"videos": {...}, "stats": {...}}
    """
    logger.info(f"=== Video Builder starting for {run_date} ===")

    scripts = _load_pass_scripts(run_date)
    if not scripts:
        logger.warning("No PASS scripts to render")
        return {"videos": {}, "stats": {"total": 0, "rendered": 0, "failed": 0}}

    service_url = os.getenv("RAILWAY_VIDEO_SERVICE_URL", "")
    if not service_url:
        logger.error("RAILWAY_VIDEO_SERVICE_URL not set — cannot render")
        return {"videos": {}, "stats": {"total": len(scripts), "rendered": 0, "failed": len(scripts)}}

    # Submit async render job, then poll for completion
    logger.info(f"Submitting {len(scripts)} scripts to Railway (async)...")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{service_url}/render/submit",
                json={
                    "scripts": scripts,
                    "date": run_date.isoformat(),
                },
            )
            resp.raise_for_status()
            job = resp.json()
    except Exception as e:
        logger.error(f"Failed to submit render job: {e}")
        return {"videos": {}, "stats": {"total": len(scripts), "rendered": 0, "failed": len(scripts)}}

    job_id = job["job_id"]
    logger.info(f"Job submitted: {job_id} ({job['total']} scripts)")

    # Poll for completion (check every 30s, max 60 min)
    MAX_POLLS = 120
    POLL_INTERVAL = 30

    for poll in range(MAX_POLLS):
        await asyncio.sleep(POLL_INTERVAL)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{service_url}/render/status/{job_id}")
                resp.raise_for_status()
                result = resp.json()
        except Exception as e:
            logger.warning(f"Poll {poll + 1} failed: {e}")
            continue

        status = result.get("status", "unknown")
        stats = result.get("stats", {})
        rendered = stats.get("rendered", 0)
        failed = stats.get("failed", 0)
        total = stats.get("total", len(scripts))

        if status in ("complete", "failed"):
            logger.info(f"Job {job_id} {status}: {rendered} rendered, {failed} failed")
            break

        logger.info(f"Poll {poll + 1}: {status} ({rendered + failed}/{total} done)")
    else:
        logger.error(f"Job {job_id} timed out after {MAX_POLLS * POLL_INTERVAL}s")
        return {"videos": {}, "stats": {"total": len(scripts), "rendered": 0, "failed": len(scripts)}}

    videos = result.get("videos", {})
    stats = result.get("stats", {})
    errors = result.get("errors", [])

    logger.info(f"Rendered: {stats.get('rendered', 0)}, Failed: {stats.get('failed', 0)}")
    for err in errors:
        logger.warning(f"Render error: {err}")

    # Save to Supabase
    video_records = []
    for brief_id, video_data in videos.items():
        dest = brief_id.split("_")[0]
        video_records.append({
            "brief_id": brief_id,
            "date": run_date.isoformat(),
            "destination": dest,
            "video_url": video_data["url"],
            "duration_seconds": video_data.get("duration"),
            "render_status": "rendered",
        })

    if video_records:
        try:
            db.save_rendered_videos(video_records)
        except Exception as e:
            logger.error(f"Failed to save video records to Supabase: {e}")

    # Save to local file
    output_file = DATA_DIR / f"videos_{run_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump({
            "date": run_date.isoformat(),
            "videos": videos,
            "errors": errors,
            "stats": stats,
        }, f, indent=2)

    logger.info(f"=== Video Builder complete: {stats.get('rendered', 0)} videos ===")
    return {"videos": videos, "stats": stats}
