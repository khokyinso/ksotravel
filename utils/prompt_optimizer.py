"""Prompt optimization tracker.

Tracks audit pass rates per agent over time, detects degradation,
and recommends model upgrades when performance drops.
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from utils import supabase_client as db

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

PASS_RATE_THRESHOLD = float(os.getenv("PROMPT_PASS_RATE_THRESHOLD", "0.50"))

MODEL_UPGRADE_MAP = {
    "claude-haiku-4-5-20251001": "claude-sonnet-4-6",
}


def _load_prompt_versions() -> dict:
    """Load prompt version config."""
    versions_file = CONFIG_DIR / "prompt_versions.json"
    if versions_file.exists():
        with open(versions_file) as f:
            return json.load(f)
    return {}


def record_daily_stats(run_date: date) -> dict:
    """Aggregate today's audit results into prompt_optimization table.

    Returns dict of stats per agent.
    """
    # Load today's audit results from file
    audit_file = DATA_DIR / f"audit_results_{run_date.isoformat()}.json"
    if not audit_file.exists():
        logger.info("No audit results file found — skipping prompt optimization stats")
        return {}

    with open(audit_file) as f:
        data = json.load(f)
    results = data.get("results", [])

    if not results:
        return {}

    # Count verdicts (all audits come from content_auditor, reflecting script_writer quality)
    pass_count = sum(1 for r in results if r.get("verdict") == "PASS")
    revise_count = sum(1 for r in results if r.get("verdict") == "REVISE")
    fail_count = sum(1 for r in results if r.get("verdict") == "FAIL")
    total = len(results)
    pass_rate = pass_count / total if total > 0 else 0.0

    # Get cost data from token tracker
    try:
        usage_summary = db.get_usage_summary(run_date)
        sw_usage = usage_summary.get("script_writer", {})
        avg_cost = sw_usage.get("cost_usd", 0) / sw_usage.get("calls", 1) if sw_usage else 0
    except Exception:
        avg_cost = 0

    versions = _load_prompt_versions()
    sw_version = versions.get("script_writer", {}).get("version", "v1")
    sw_model = versions.get("script_writer", {}).get("model", "claude-sonnet-4-6")

    stats = {
        "date": run_date.isoformat(),
        "agent_name": "script_writer",
        "model": sw_model,
        "total_calls": total,
        "pass_count": pass_count,
        "revise_count": revise_count,
        "fail_count": fail_count,
        "pass_rate": round(pass_rate, 4),
        "avg_cost_per_call": round(avg_cost, 6),
        "prompt_version": sw_version,
    }

    # Save to Supabase
    try:
        db.upsert_prompt_stats(stats)
        logger.info(f"Saved prompt optimization stats: pass_rate={pass_rate:.1%}")
    except Exception as e:
        logger.warning(f"Failed to save prompt stats to Supabase: {e}")

    # Save locally
    stats_file = DATA_DIR / f"prompt_stats_{run_date.isoformat()}.json"
    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2)

    return stats


def check_degradation(agent_name: str = "script_writer", lookback_days: int = 7) -> dict | None:
    """Check if an agent's pass rate has degraded.

    Returns recommendation dict if degraded, None if healthy.
    Triggers when: 3-day avg < threshold AND 3-day avg < 7-day avg by >10%.
    """
    today = date.today()
    start = today - timedelta(days=lookback_days)

    try:
        history = db.get_prompt_stats_range(agent_name, start, today)
    except Exception:
        # Fall back to local files
        history = []
        for i in range(lookback_days):
            d = today - timedelta(days=i)
            stats_file = DATA_DIR / f"prompt_stats_{d.isoformat()}.json"
            if stats_file.exists():
                with open(stats_file) as f:
                    history.append(json.load(f))

    if len(history) < 3:
        return None  # Not enough data

    # Calculate averages
    recent_3 = history[-3:]
    all_rates = [h.get("pass_rate", 0) for h in history if h.get("pass_rate") is not None]
    recent_rates = [h.get("pass_rate", 0) for h in recent_3 if h.get("pass_rate") is not None]

    if not recent_rates or not all_rates:
        return None

    avg_3day = sum(recent_rates) / len(recent_rates)
    avg_7day = sum(all_rates) / len(all_rates)

    if avg_3day < PASS_RATE_THRESHOLD and avg_3day < avg_7day - 0.10:
        current_model = history[-1].get("model", "unknown")
        suggested_model = MODEL_UPGRADE_MAP.get(current_model)

        return {
            "agent_name": agent_name,
            "current_model": current_model,
            "avg_3day_pass_rate": round(avg_3day, 4),
            "avg_7day_pass_rate": round(avg_7day, 4),
            "threshold": PASS_RATE_THRESHOLD,
            "recommendation": (
                f"Upgrade to {suggested_model}" if suggested_model
                else "Review and optimize prompts"
            ),
        }

    return None


def get_optimization_report(run_date: date) -> str:
    """Generate a text summary for the daily report."""
    lines = [f"=== Prompt Optimization Report — {run_date} ==="]

    # Today's stats
    stats_file = DATA_DIR / f"prompt_stats_{run_date.isoformat()}.json"
    if stats_file.exists():
        with open(stats_file) as f:
            stats = json.load(f)
        pass_rate = stats.get("pass_rate", 0)
        total = stats.get("total_calls", 0)
        lines.append(
            f"  Script Writer: {pass_rate:.1%} pass rate "
            f"({stats.get('pass_count', 0)}/{total} passed, "
            f"{stats.get('revise_count', 0)} revise, {stats.get('fail_count', 0)} fail)"
        )
        if stats.get("avg_cost_per_call"):
            lines.append(f"  Avg cost per script: ${stats['avg_cost_per_call']:.4f}")
    else:
        lines.append("  No audit data available for today")

    # Degradation check
    degradation = check_degradation()
    if degradation:
        lines.append("")
        lines.append(f"  ⚠️ DEGRADATION DETECTED for {degradation['agent_name']}:")
        lines.append(f"    3-day avg: {degradation['avg_3day_pass_rate']:.1%}")
        lines.append(f"    7-day avg: {degradation['avg_7day_pass_rate']:.1%}")
        lines.append(f"    Recommendation: {degradation['recommendation']}")
    else:
        lines.append("  No degradation detected")

    report = "\n".join(lines)
    logger.info(report)
    return report
