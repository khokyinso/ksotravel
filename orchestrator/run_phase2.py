"""Phase 2 Orchestrator — Script Writing + Audit

Runs Agents 5-6 in sequence:
  5. Script Writer — 96 scripts in parallel batches of 12
  6. Content Auditor — 96 audits in parallel, PASS/REVISE/FAIL

Revision loop: REVISE scripts are sent back to Agent 5 (max 2 loops).

Output: data/scripts_{date}.json + data/audit_results_{date}.json

Usage:
    python -m orchestrator.run_phase2
    python -m orchestrator.run_phase2 --date 2026-03-23
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
    LOG_DIR / "phase2_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="1 day",
    retention="30 days",
)


async def run_phase2(run_date: date) -> dict:
    """Execute Phase 2 pipeline: Agents 5, 6 with revision loop."""
    from agents import script_writer, content_auditor

    start_time = datetime.now()
    logger.info(f"{'='*60}")
    logger.info(f"PHASE 2 — Script Writing + Audit — {run_date}")
    logger.info(f"{'='*60}")

    results = {}
    max_loops = int(__import__("os").getenv("MAX_AUDIT_REVISION_LOOPS", "2"))

    # Step 1: Write all scripts
    logger.info("Step 1: Running Script Writer (Agent 5)...")
    try:
        writer_result = await script_writer.run(run_date)
        results["script_writer"] = writer_result["stats"]
        logger.info(
            f"Script Writer: {writer_result['stats']['total_scripts']} scripts "
            f"({writer_result['stats']['valid']} valid)"
        )
    except Exception as e:
        logger.error(f"Script Writer failed: {e}")
        results["script_writer"] = {"error": str(e)}
        # Can't proceed without scripts
        return _finalize(results, run_date, start_time)

    # Step 2: Audit all scripts
    logger.info("Step 2: Running Content Auditor (Agent 6)...")
    try:
        audit_result = await content_auditor.run(run_date)
        results["content_auditor"] = audit_result["stats"]
        logger.info(
            f"Content Auditor: {audit_result['stats']['passed']} PASS, "
            f"{audit_result['stats']['revise']} REVISE, "
            f"{audit_result['stats']['failed']} FAIL"
        )
    except Exception as e:
        logger.error(f"Content Auditor failed: {e}")
        results["content_auditor"] = {"error": str(e)}
        return _finalize(results, run_date, start_time)

    # Step 3: Revision loop for REVISE scripts
    revise_ids = [
        r["brief_id"]
        for r in audit_result.get("audit_results", [])
        if r.get("verdict") == "REVISE"
    ]

    loop_count = 0
    while revise_ids and loop_count < max_loops:
        loop_count += 1
        logger.info(
            f"Revision loop {loop_count}/{max_loops}: "
            f"Re-writing {len(revise_ids)} scripts..."
        )

        # Load current briefs and filter to REVISE ones
        DATA_DIR = Path(__file__).parent.parent / "data"
        briefs_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
        with open(briefs_file) as f:
            all_briefs = json.load(f).get("briefs", [])
        revise_briefs = [b for b in all_briefs if b.get("brief_id") in revise_ids]

        # Re-write just the REVISE scripts
        cta_winner = writer_result["stats"].get("cta_winner", "A")
        try:
            revised_scripts = await script_writer.write_batch(revise_briefs, cta_winner)
        except Exception as e:
            logger.error(f"Revision loop {loop_count} write failed: {e}")
            break

        # Update scripts file with revised versions
        scripts_file = DATA_DIR / f"scripts_{run_date.isoformat()}.json"
        with open(scripts_file) as f:
            scripts_data = json.load(f)

        # Replace revised scripts
        revised_map = {s["brief_id"]: s for s in revised_scripts}
        updated_scripts = []
        for s in scripts_data.get("scripts", []):
            if s["brief_id"] in revised_map:
                updated_scripts.append(revised_map[s["brief_id"]])
            else:
                updated_scripts.append(s)
        scripts_data["scripts"] = updated_scripts

        with open(scripts_file, "w") as f:
            json.dump(scripts_data, f, indent=2)

        # Re-audit just the revised scripts
        briefs_map = {b["brief_id"]: b for b in all_briefs}
        try:
            re_audit = await content_auditor.audit_batch(revised_scripts, briefs_map)
        except Exception as e:
            logger.error(f"Revision loop {loop_count} audit failed: {e}")
            break

        # Update audit results file
        audit_file = DATA_DIR / f"audit_results_{run_date.isoformat()}.json"
        with open(audit_file) as f:
            audit_data = json.load(f)

        re_audit_map = {r["brief_id"]: r for r in re_audit}
        updated_results = []
        for r in audit_data.get("results", []):
            if r["brief_id"] in re_audit_map:
                updated_results.append(re_audit_map[r["brief_id"]])
            else:
                updated_results.append(r)
        audit_data["results"] = updated_results

        # Recount
        passed = sum(1 for r in updated_results if r.get("verdict") == "PASS")
        revise_count = sum(1 for r in updated_results if r.get("verdict") == "REVISE")
        failed = sum(1 for r in updated_results if r.get("verdict") == "FAIL")
        audit_data["passed"] = passed
        audit_data["revise"] = revise_count
        audit_data["failed"] = failed

        with open(audit_file, "w") as f:
            json.dump(audit_data, f, indent=2)

        # Check remaining REVISE
        new_pass = sum(1 for r in re_audit if r.get("verdict") == "PASS")
        still_revise = [
            r["brief_id"] for r in re_audit if r.get("verdict") == "REVISE"
        ]
        logger.info(
            f"Revision loop {loop_count}: {new_pass} now PASS, "
            f"{len(still_revise)} still REVISE"
        )
        revise_ids = still_revise

    # Final stats
    results["revision_loops"] = loop_count
    results["final_audit"] = {
        "passed": audit_data.get("passed", 0) if loop_count > 0 else audit_result["stats"]["passed"],
        "revise": audit_data.get("revise", 0) if loop_count > 0 else audit_result["stats"]["revise"],
        "failed": audit_data.get("failed", 0) if loop_count > 0 else audit_result["stats"]["failed"],
    }

    # Step 4: Run Performance Analyzer (Agent 15)
    logger.info("Step 4: Running Performance Analyzer (Agent 15)...")
    try:
        from agents import performance_analyzer
        perf_result = await performance_analyzer.run(run_date)
        results["performance_analyzer"] = perf_result
    except Exception as e:
        logger.error(f"Performance Analyzer failed: {e}")
        results["performance_analyzer"] = {"error": str(e)}

    # Step 5: Run Prompt Optimization tracking
    logger.info("Step 5: Running Prompt Optimization tracking...")
    try:
        from utils.prompt_optimizer import record_daily_stats, get_optimization_report
        opt_stats = record_daily_stats(run_date)
        results["prompt_optimization"] = opt_stats
        get_optimization_report(run_date)
    except Exception as e:
        logger.error(f"Prompt optimization tracking failed: {e}")

    return _finalize(results, run_date, start_time)


def _finalize(results: dict, run_date: date, start_time: datetime) -> dict:
    """Build summary and save."""
    elapsed = (datetime.now() - start_time).total_seconds()

    # Cost summary
    from utils.token_tracker import get_session_summary, check_cost_alert
    cost_summary = get_session_summary()
    check_cost_alert()

    summary = {
        "date": run_date.isoformat(),
        "phase": "phase2",
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
        "cost": cost_summary,
    }

    DATA_DIR = Path(__file__).parent.parent / "data"
    summary_file = DATA_DIR / f"phase2_summary_{run_date.isoformat()}.json"
    with open(summary_file, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    final = results.get("final_audit", {})
    logger.info(f"{'='*60}")
    logger.info(f"PHASE 2 COMPLETE in {elapsed:.1f}s")
    logger.info(f"Scripts: {results.get('script_writer', {}).get('total_scripts', 'ERROR')}")
    logger.info(f"Final: {final.get('passed', '?')} PASS, {final.get('revise', '?')} REVISE, {final.get('failed', '?')} FAIL")
    logger.info(f"Revision loops: {results.get('revision_loops', 0)}")
    logger.info(f"Cost: ${cost_summary.get('total_cost_usd', 0):.4f} ({cost_summary.get('total_calls', 0)} API calls)")
    logger.info(f"Performance weights: {results.get('performance_analyzer', {}).get('weights_updated', 'N/A')}")
    logger.info(f"Summary: {summary_file}")
    logger.info(f"{'='*60}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run Phase 2 — Script Writing + Audit")
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

    result = asyncio.run(run_phase2(run_date))

    has_errors = any(
        "error" in v for v in result.get("results", {}).values() if isinstance(v, dict)
    )
    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
