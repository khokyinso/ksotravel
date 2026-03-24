"""Phase 1 Orchestrator — Intelligence Layer

Runs Agents 1-3 in sequence:
  1. Trend Scout (Agent 1) — 12+ trends per destination
  2. Deal Harvester (Agent 2) — 10+ deals per destination (parallel with Agent 1)
  3. Content Strategist (Agent 3) — 8 briefs per channel (96 total)

Output: data/briefs_{date}.json with 96 content briefs ready for Phase 2.

Usage:
    python -m orchestrator.run_phase1
    python -m orchestrator.run_phase1 --date 2026-03-23
"""

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from loguru import logger

# Configure logging
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<7} | {message}")
logger.add(
    LOG_DIR / "phase1_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="1 day",
    retention="30 days",
)


async def run_phase1(run_date: date) -> dict:
    """Execute Phase 1 pipeline: Agents 1, 2, 3."""
    from agents import trend_scout, deal_harvester, content_strategist

    start_time = datetime.now()
    logger.info(f"{'='*60}")
    logger.info(f"PHASE 1 — Intelligence Layer — {run_date}")
    logger.info(f"{'='*60}")

    results = {}

    # Step 1 & 2: Run Trend Scout and Deal Harvester in PARALLEL
    logger.info("Step 1-2: Running Trend Scout + Deal Harvester in parallel...")
    trend_task = trend_scout.run(run_date)
    deal_task = deal_harvester.run(run_date)

    trend_result, deal_result = await asyncio.gather(
        trend_task, deal_task, return_exceptions=True
    )

    if isinstance(trend_result, Exception):
        logger.error(f"Trend Scout failed: {trend_result}")
        results["trend_scout"] = {"error": str(trend_result)}
    else:
        results["trend_scout"] = trend_result["stats"]
        logger.info(f"Trend Scout: {trend_result['stats']['total_trends']} trends")

    if isinstance(deal_result, Exception):
        logger.error(f"Deal Harvester failed: {deal_result}")
        results["deal_harvester"] = {"error": str(deal_result)}
    else:
        results["deal_harvester"] = deal_result["stats"]
        logger.info(f"Deal Harvester: {deal_result['stats']['total_deals']} deals")

    # Step 3: Run Content Strategist (needs trends + deals)
    logger.info("Step 3: Running Content Strategist...")
    try:
        strategist_result = await content_strategist.run(run_date)
        results["content_strategist"] = strategist_result["stats"]
        logger.info(
            f"Content Strategist: {strategist_result['stats']['total_briefs']}/96 briefs"
        )
    except Exception as e:
        logger.error(f"Content Strategist failed: {e}")
        results["content_strategist"] = {"error": str(e)}

    # Summary
    elapsed = (datetime.now() - start_time).total_seconds()
    summary = {
        "date": run_date.isoformat(),
        "phase": "phase1",
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
    }

    # Cost summary
    from utils.token_tracker import get_session_summary, check_cost_alert
    cost_summary = get_session_summary()
    summary["cost"] = cost_summary
    check_cost_alert()

    # Save summary
    DATA_DIR = Path(__file__).parent.parent / "data"
    summary_file = DATA_DIR / f"phase1_summary_{run_date.isoformat()}.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"{'='*60}")
    logger.info(f"PHASE 1 COMPLETE in {elapsed:.1f}s")
    logger.info(f"Trends: {results.get('trend_scout', {}).get('total_trends', 'ERROR')}")
    logger.info(f"Deals: {results.get('deal_harvester', {}).get('total_deals', 'ERROR')}")
    logger.info(f"Briefs: {results.get('content_strategist', {}).get('total_briefs', 'ERROR')}/96")
    logger.info(f"Cost: ${cost_summary.get('total_cost_usd', 0):.4f} ({cost_summary.get('total_calls', 0)} API calls)")
    logger.info(f"Summary: {summary_file}")
    logger.info(f"{'='*60}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 — Intelligence Layer")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Run date in YYYY-MM-DD format (default: today)",
    )
    args = parser.parse_args()

    if args.date:
        run_date = date.fromisoformat(args.date)
    else:
        run_date = date.today()

    result = asyncio.run(run_phase1(run_date))

    # Exit with error code if any agent failed
    has_errors = any(
        "error" in v for v in result.get("results", {}).values() if isinstance(v, dict)
    )
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
