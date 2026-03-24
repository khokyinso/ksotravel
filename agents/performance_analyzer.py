"""Agent 15: Performance Analyzer

Analyzes audit results and published video data to compute performance weights.
Writes weights back to Supabase for Agents 1, 2, 3, and 5 to consume.

No LLM call needed — pure data analysis agent.

Schedule: After Phase 2 completes daily
Output: Updated performance_weights table in Supabase
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from utils import supabase_client as db
from config.constants import DESTINATIONS

DATA_DIR = Path(__file__).parent.parent / "data"


def _load_briefs_from_files(lookback_days: int = 30) -> list[dict]:
    """Load briefs from local JSON files for the lookback window."""
    all_briefs = []
    today = date.today()
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        briefs_file = DATA_DIR / f"briefs_{d.isoformat()}.json"
        if briefs_file.exists():
            with open(briefs_file) as f:
                data = json.load(f)
            all_briefs.extend(data.get("briefs", []))
    return all_briefs


def _load_audit_results_from_files(lookback_days: int = 30) -> list[dict]:
    """Load audit results from local JSON files for the lookback window."""
    all_results = []
    today = date.today()
    for i in range(lookback_days):
        d = today - timedelta(days=i)
        audit_file = DATA_DIR / f"audit_results_{d.isoformat()}.json"
        if audit_file.exists():
            with open(audit_file) as f:
                data = json.load(f)
            all_results.extend(data.get("results", []))
    return all_results


def _compute_weights_from_audits(
    briefs: list[dict], audit_results: list[dict]
) -> list[dict]:
    """Compute performance weights from audit verdicts.

    For each destination, calculates which hook_angles, video_formats,
    content_categories, and cta_templates get PASS verdicts most often.
    Normalizes to 0.0-1.0 scale where best performer = 1.0.
    """
    # Index briefs by brief_id
    briefs_map = {b.get("brief_id", ""): b for b in briefs if "brief_id" in b}

    # Index audit results by brief_id
    audit_map = {}
    for r in audit_results:
        bid = r.get("brief_id", "")
        if bid:
            audit_map[bid] = r

    # Collect pass counts per destination per metric
    # Structure: {destination: {metric_type: {metric_key: {"pass": N, "total": N}}}}
    stats: dict[str, dict[str, dict[str, dict]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: {"pass": 0, "total": 0}))
    )

    for brief_id, brief in briefs_map.items():
        dest = brief.get("destination", "")
        if not dest:
            continue

        audit = audit_map.get(brief_id)
        is_pass = audit and audit.get("verdict") == "PASS" if audit else False

        # Track hook_angle
        hook = brief.get("hook_angle", "")
        if hook:
            stats[dest]["hook_angle"][hook]["total"] += 1
            if is_pass:
                stats[dest]["hook_angle"][hook]["pass"] += 1

        # Track video_format
        fmt = brief.get("video_format", "")
        if fmt:
            stats[dest]["video_format"][fmt]["total"] += 1
            if is_pass:
                stats[dest]["video_format"][fmt]["pass"] += 1

        # Track content_category
        cat = brief.get("content_category", "")
        if cat:
            stats[dest]["content_category"][cat]["total"] += 1
            if is_pass:
                stats[dest]["content_category"][cat]["pass"] += 1

    # Convert to normalized weights
    weights = []
    for dest, metric_types in stats.items():
        for metric_type, keys in metric_types.items():
            # Calculate pass rate for each key
            rates = {}
            for key, counts in keys.items():
                if counts["total"] > 0:
                    rates[key] = counts["pass"] / counts["total"]
                else:
                    rates[key] = 0.0

            # Normalize: best performer = 1.0
            max_rate = max(rates.values()) if rates else 1.0
            if max_rate == 0:
                max_rate = 1.0

            for key, rate in rates.items():
                weights.append({
                    "destination": dest,
                    "metric_type": metric_type,
                    "metric_key": key,
                    "weight": round(rate / max_rate, 4),
                })

    return weights


def _compute_cta_weights(briefs: list[dict], audit_results: list[dict]) -> list[dict]:
    """Compute which CTA template (A/B/C/D) performs best globally."""
    # This requires knowing which CTA was used per script.
    # For now, track globally — Agent 14 will refine this later.
    # Simple: count PASS verdicts across all destinations
    cta_counts: dict[str, dict] = defaultdict(lambda: {"pass": 0, "total": 0})

    audit_map = {r.get("brief_id", ""): r for r in audit_results if "brief_id" in r}

    for brief in briefs:
        bid = brief.get("brief_id", "")
        # We don't store CTA template in briefs, so default to tracking by slot
        # Once we have real CTA data from Agent 14, this improves
        audit = audit_map.get(bid)
        if audit:
            cta_counts["A"]["total"] += 1  # placeholder
            if audit.get("verdict") == "PASS":
                cta_counts["A"]["pass"] += 1

    weights = []
    for cta, counts in cta_counts.items():
        rate = counts["pass"] / counts["total"] if counts["total"] > 0 else 0.0
        weights.append({
            "destination": "global",
            "metric_type": "cta_winner",
            "metric_key": cta,
            "weight": round(rate, 4),
        })

    return weights


async def run(run_date: date) -> dict:
    """Run performance analysis and update weights.

    Returns summary dict with counts and top performers.
    """
    logger.info(f"=== Performance Analyzer starting for {run_date} ===")

    # Load data from files (primary) and Supabase (fallback)
    briefs = _load_briefs_from_files(lookback_days=30)
    audit_results = _load_audit_results_from_files(lookback_days=30)

    # Also try Supabase
    try:
        start = run_date - timedelta(days=30)
        db_audits = db.get_audit_results_range(start, run_date)
        if db_audits and not audit_results:
            audit_results = db_audits
    except Exception as e:
        logger.debug(f"Supabase audit query failed (using files): {e}")

    if not briefs:
        logger.warning("No briefs found for analysis — skipping weight computation")
        return {"weights_updated": 0, "briefs_analyzed": 0, "audits_analyzed": 0}

    logger.info(f"Analyzing {len(briefs)} briefs and {len(audit_results)} audit results")

    # Compute weights
    metric_weights = _compute_weights_from_audits(briefs, audit_results)
    cta_weights = _compute_cta_weights(briefs, audit_results)
    all_weights = metric_weights + cta_weights

    # Save to Supabase
    saved = 0
    if all_weights:
        try:
            saved = db.upsert_performance_weights(all_weights)
            logger.info(f"Upserted {saved} performance weights to Supabase")
        except Exception as e:
            logger.error(f"Failed to save weights to Supabase: {e}")

    # Save to local file for debugging
    weights_file = DATA_DIR / f"performance_weights_{run_date.isoformat()}.json"
    with open(weights_file, "w") as f:
        json.dump({"weights": all_weights, "date": run_date.isoformat()}, f, indent=2)

    # Generate summary
    dest_count = len(set(w["destination"] for w in all_weights))
    metric_types = set(w["metric_type"] for w in all_weights)

    summary = {
        "weights_updated": saved,
        "briefs_analyzed": len(briefs),
        "audits_analyzed": len(audit_results),
        "destinations": dest_count,
        "metric_types": list(metric_types),
    }

    # Log top performers per destination
    for dest in DESTINATIONS:
        dest_weights = [w for w in all_weights if w["destination"] == dest]
        if dest_weights:
            top = max(dest_weights, key=lambda w: w["weight"])
            logger.info(
                f"  {dest}: top {top['metric_type']}={top['metric_key']} "
                f"(weight={top['weight']})"
            )

    logger.info(f"=== Performance Analyzer complete: {saved} weights updated ===")
    return summary
