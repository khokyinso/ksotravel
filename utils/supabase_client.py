"""Supabase client wrapper for KSO Travel Automation."""

import os
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv
from loguru import logger
from supabase import create_client, Client

load_dotenv(override=True)


def get_client() -> Client:
    """Create and return a Supabase client."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(url, key)


_client: Client | None = None


def client() -> Client:
    """Get or create singleton Supabase client."""
    global _client
    if _client is None:
        _client = get_client()
    return _client


# ── Trends ────────────────────────────────────────────────────────────────


def save_trends(trends: list[dict], run_date: date) -> int:
    """Save trend signals to Supabase. Returns count saved."""
    rows = []
    for t in trends:
        rows.append({
            "date": run_date.isoformat(),
            "destination": t["destination"],
            "topic": t["topic"],
            "hook_angle": t["hook_angle"],
            "urgency": t.get("urgency", "medium"),
            "search_volume_trend": t.get("search_volume_trend"),
            "content_category": t["content_category"],
            "suggested_hook": t.get("suggested_hook"),
            "suggested_length_seconds": t.get("suggested_length_seconds", 30),
            "video_format": t.get("video_format", "green_screen_text"),
            "source": t.get("source"),
            "source_signal": t.get("source_signal"),
        })
    if rows:
        client().table("trends").insert(rows).execute()
        logger.info(f"Saved {len(rows)} trends for {run_date}")
    return len(rows)


def get_trends(run_date: date, destination: str | None = None) -> list[dict]:
    """Fetch trends for a date, optionally filtered by destination."""
    q = client().table("trends").select("*").eq("date", run_date.isoformat())
    if destination:
        q = q.eq("destination", destination)
    result = q.execute()
    return result.data


# ── Deals ─────────────────────────────────────────────────────────────────


def save_deals(deals: list[dict], run_date: date) -> int:
    """Save scored deals to Supabase. Returns count saved."""
    rows = []
    for d in deals:
        rows.append({
            "date": run_date.isoformat(),
            "destination": d["destination"],
            "platform": d["platform"],
            "product_name": d["product_name"],
            "affiliate_url": d["affiliate_url"],
            "price_usd": d.get("price_usd"),
            "commission_pct": d.get("commission_pct"),
            "deal_score": d["deal_score"],
            "urgency": d.get("urgency"),
            "category": d["category"],
        })
    if rows:
        client().table("deals").insert(rows).execute()
        logger.info(f"Saved {len(rows)} deals for {run_date}")
    return len(rows)


def get_deals(run_date: date, destination: str | None = None) -> list[dict]:
    """Fetch deals for a date, optionally filtered by destination."""
    q = client().table("deals").select("*").eq("date", run_date.isoformat())
    if destination:
        q = q.eq("destination", destination)
    result = q.order("deal_score", desc=True).execute()
    return result.data


# ── Briefs ────────────────────────────────────────────────────────────────


def save_briefs(briefs: list[dict]) -> int:
    """Save content briefs to Supabase. Returns count saved."""
    rows = []
    for b in briefs:
        rows.append({
            "brief_id": b["brief_id"],
            "date": b["date"] if isinstance(b["date"], str) else b["date"].isoformat(),
            "channel": b["channel"],
            "destination": b["destination"],
            "topic": b["topic"],
            "hook_angle": b["hook_angle"],
            "hook_text": b["hook_text"],
            "content_category": b["content_category"],
            "target_length_seconds": b["target_length_seconds"],
            "is_sample_video": b.get("is_sample_video", False),
            "deal_platform": b.get("deal", {}).get("platform") if b.get("deal") else None,
            "deal_product": b.get("deal", {}).get("product") if b.get("deal") else None,
            "deal_url": b.get("deal", {}).get("url") if b.get("deal") else None,
            "deal_price_usd": b.get("deal", {}).get("price_usd") if b.get("deal") else None,
            "deal_commission_pct": b.get("deal", {}).get("commission_pct") if b.get("deal") else None,
            "comment_trigger_phrase": b["comment_trigger_phrase"],
            "dm_payload_type": b.get("dm_payload_type"),
            "video_format": b.get("video_format", "green_screen_text"),
            "posting_slot": b.get("posting_slot"),
            "posting_time_est": b.get("posting_time_est"),
            "source_signal": b.get("source_signal"),
            "status": "draft",
        })
    if rows:
        client().table("briefs").insert(rows).execute()
        logger.info(f"Saved {len(rows)} briefs")
    return len(rows)


def get_briefs(run_date: date, channel: str | None = None) -> list[dict]:
    """Fetch briefs for a date, optionally filtered by channel."""
    q = client().table("briefs").select("*").eq("date", run_date.isoformat())
    if channel:
        q = q.eq("channel", channel)
    result = q.execute()
    return result.data


# ── Scripts ───────────────────────────────────────────────────────────────


def save_scripts(scripts: list[dict]) -> int:
    """Save scripts to Supabase. Returns count saved."""
    rows = []
    for s in scripts:
        rows.append({
            "brief_id": s["brief_id"],
            "script_lines": s.get("script_lines", []),
            "caption": s.get("caption", ""),
            "hashtags": s.get("hashtags", []),
            "affiliate_url": s.get("affiliate_url", ""),
            "geotag": s.get("geotag", ""),
            "target_length_seconds": s.get("target_length_seconds", 30),
            "video_format": s.get("video_format", "green_screen_text"),
            "is_valid": s.get("is_valid", False),
            "validation_issues": s.get("validation_issues", []),
        })
    if rows:
        client().table("scripts").upsert(rows, on_conflict="brief_id").execute()
        logger.info(f"Saved {len(rows)} scripts")
    return len(rows)


# ── Audit Results ─────────────────────────────────────────────────────────


def save_audit_results(results: list[dict]) -> int:
    """Save audit results to Supabase. Returns count saved."""
    rows = []
    for r in results:
        rows.append({
            "brief_id": r["brief_id"],
            "verdict": r.get("verdict", "FAIL"),
            "checks_passed": r.get("checks_passed", 0),
            "checks_total": r.get("checks_total", 0),
            "failed_checks": r.get("failed_checks", []),
            "revision_notes": r.get("revision_notes"),
            "severity": r.get("severity", "none"),
        })
    if rows:
        client().table("audit_results").upsert(rows, on_conflict="brief_id").execute()
        logger.info(f"Saved {len(rows)} audit results")
    return len(rows)


# ── Published Videos ──────────────────────────────────────────────────────


def get_recent_topics(destination: str, days: int = 60) -> list[str]:
    """Get topics published in the last N days for a destination."""
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    result = (
        client()
        .table("published_videos")
        .select("topic")
        .eq("destination", destination)
        .gte("published_at", cutoff)
        .execute()
    )
    return [r["topic"] for r in result.data]


# ── Pipeline Runs ─────────────────────────────────────────────────────────


def log_pipeline_run(
    run_date: date, phase: str, agent: str, status: str = "running"
) -> int:
    """Log a pipeline run. Returns the run ID."""
    result = (
        client()
        .table("pipeline_runs")
        .insert({
            "date": run_date.isoformat(),
            "phase": phase,
            "agent": agent,
            "status": status,
        })
        .execute()
    )
    return result.data[0]["id"]


def update_pipeline_run(
    run_id: int,
    status: str,
    briefs_generated: int = 0,
    errors: list | None = None,
) -> None:
    """Update a pipeline run status."""
    client().table("pipeline_runs").update({
        "status": status,
        "completed_at": datetime.utcnow().isoformat(),
        "briefs_generated": briefs_generated,
        "errors": errors or [],
    }).eq("id", run_id).execute()


# ── Performance Weights (read-only in Phase 1) ───────────────────────────


def get_performance_weights(
    destination: str, metric_type: str | None = None
) -> dict[str, float]:
    """Get performance weights for a destination. Optionally filter by metric_type."""
    q = (
        client()
        .table("performance_weights")
        .select("metric_key, weight")
        .eq("destination", destination)
    )
    if metric_type:
        q = q.eq("metric_type", metric_type)
    result = q.execute()
    return {r["metric_key"]: float(r["weight"]) for r in result.data}


def upsert_performance_weights(weights: list[dict]) -> int:
    """Upsert performance weights. Each dict: destination, metric_type, metric_key, weight."""
    if not weights:
        return 0
    client().table("performance_weights").upsert(
        weights, on_conflict="destination,metric_type,metric_key"
    ).execute()
    return len(weights)


# ── API Usage Logs ───────────────────────────────────────────────────────


def save_usage_log(record: dict) -> None:
    """Insert a single API usage log record."""
    client().table("api_usage_logs").insert(record).execute()


def get_usage_summary(run_date: date) -> dict:
    """Get aggregated API cost by agent for a date."""
    result = (
        client()
        .table("api_usage_logs")
        .select("agent_name, input_tokens, output_tokens, cost_usd")
        .eq("date", run_date.isoformat())
        .execute()
    )
    summary: dict[str, dict] = {}
    for r in result.data:
        agent = r["agent_name"]
        if agent not in summary:
            summary[agent] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        summary[agent]["calls"] += 1
        summary[agent]["input_tokens"] += r["input_tokens"]
        summary[agent]["output_tokens"] += r["output_tokens"]
        summary[agent]["cost_usd"] += float(r["cost_usd"])
    return summary


# ── Audit Results (range query for Agent 15) ─────────────────────────────


def get_audit_results_range(start_date: date, end_date: date) -> list[dict]:
    """Get audit results in a date range. Joins with briefs for destination/hook data."""
    result = (
        client()
        .table("audit_results")
        .select("*")
        .gte("created_at", start_date.isoformat())
        .lte("created_at", end_date.isoformat() + "T23:59:59")
        .execute()
    )
    return result.data


# ── Prompt Optimization ──────────────────────────────────────────────────


def upsert_prompt_stats(stats: dict) -> None:
    """Upsert daily prompt optimization stats."""
    client().table("prompt_optimization").upsert(
        stats, on_conflict="date,agent_name,model"
    ).execute()


def get_prompt_stats_range(
    agent_name: str, start_date: date, end_date: date
) -> list[dict]:
    """Get prompt optimization stats for an agent over a date range."""
    result = (
        client()
        .table("prompt_optimization")
        .select("*")
        .eq("agent_name", agent_name)
        .gte("date", start_date.isoformat())
        .lte("date", end_date.isoformat())
        .order("date")
        .execute()
    )
    return result.data


# ── Rendered Videos ──────────────────────────────────────────────────────


def save_rendered_videos(videos: list[dict]) -> int:
    """Save rendered video records to Supabase. Returns count saved."""
    if not videos:
        return 0
    client().table("rendered_videos").upsert(
        videos, on_conflict="brief_id"
    ).execute()
    logger.info(f"Saved {len(videos)} rendered videos")
    return len(videos)


def save_visual_qa_results(results: list[dict], run_date: date) -> int:
    """Save visual QA results to Supabase. Returns count saved."""
    rows = []
    for r in results:
        rows.append({
            "brief_id": r["brief_id"],
            "date": run_date.isoformat(),
            "overall_score": r.get("overall_score", 0),
            "hook_visibility": r.get("hook_visibility", 0),
            "text_readability": r.get("text_readability", 0),
            "visual_consistency": r.get("visual_consistency", 0),
            "format_compliance": r.get("format_compliance", 0),
            "cta_placement": r.get("cta_placement", 0),
            "verdict": r.get("verdict", "REJECT"),
            "issues": r.get("issues", []),
            "notes": r.get("notes", ""),
        })
    if rows:
        client().table("visual_qa_results").upsert(
            rows, on_conflict="brief_id"
        ).execute()
        logger.info(f"Saved {len(rows)} visual QA results")
    return len(rows)


def approve_channel_videos(destination: str, run_date: date) -> int:
    """Mark all rendered videos for a destination as approved."""
    result = (
        client()
        .table("rendered_videos")
        .update({
            "render_status": "approved",
            "approved_at": datetime.utcnow().isoformat(),
        })
        .eq("destination", destination)
        .eq("date", run_date.isoformat())
        .eq("render_status", "rendered")
        .execute()
    )
    count = len(result.data) if result.data else 0
    logger.info(f"Approved {count} videos for {destination}")
    return count


def reject_channel_videos(destination: str, run_date: date) -> int:
    """Mark all rendered videos for a destination as rejected."""
    result = (
        client()
        .table("rendered_videos")
        .update({"render_status": "rejected"})
        .eq("destination", destination)
        .eq("date", run_date.isoformat())
        .eq("render_status", "rendered")
        .execute()
    )
    count = len(result.data) if result.data else 0
    logger.info(f"Rejected {count} videos for {destination}")
    return count
