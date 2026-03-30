"""Agent 6: Content Auditor

Quality and accuracy gate. Nothing proceeds to video production without clearing all checks.
Supports PASS/REVISE/FAIL verdicts with max 2 revision loops back to Agent 5.

Model: Claude Sonnet 4.6
Schedule: 6:30 AM EST — parallel audits
Output: data/audit_results_{date}.json
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from loguru import logger

from utils import supabase_client as db

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

MAX_REVISION_LOOPS = int(os.getenv("MAX_AUDIT_REVISION_LOOPS", "2"))
BATCH_SIZE = 12

AUDIT_SYSTEM_PROMPT = """You are the Content Auditor for @kso.travel channels.
Your job is to audit TikTok/Reels scripts against their briefs.

SCRIPT STYLE (KSO format):
- Line 1 = Series title (e.g. "Japan Travel Tip #3"). This is NOT a hook — it's a label.
- Line 2 = Relatable hook starting with "If you're..." or similar conversational opener. THIS IS CORRECT AND EXPECTED.
- Middle lines = Key facts, tips, prices. Short and punchy.
- Last line = Soft CTA or follow prompt

STANDARD CHECKLIST:
1. Line 1 is a series title or topic label (NOT a hook — titles like "Japan Travel Tip #3" are correct)
2. Line count is within ±2 of target (15s=4, 30s=5, 45s=6, 60s=7). DO NOT use old targets like 7 or 10 — those are outdated.
3. No line exceeds 15 words (short punchy blocks for phone screen)
4. Trigger phrase appears somewhere in the script
5. Script includes a CTA (comment prompt or follow prompt)
6. Real USD prices or specific numbers included (not vague)
7. Real product/place names included (not generic)
8. Caption ≤150 chars before hashtags
9. 4-6 hashtags included
10. Voice is conversational and specific ("you", "your", real details)
11. Deal info matches brief (if deal assigned)

IMPORTANT — These are CORRECT and should PASS:
- "If you're planning to come to Japan..." — this is the KSO signature style, NOT blacklisted
- "If you're traveling to..." — CORRECT opener, do NOT fail this
- Line 1 being a title like "Japan Travel Tip #5" — CORRECT, NOT a hook

DESTINATION-SPECIFIC CHECKS:
- China: Visa info must be verifiable, no political commentary
- Turkey: ALL prices must be in USD — never Turkish Lira
- Poland: Auschwitz content (if any) must use respectful tone

VERDICT RULES:
- PASS: All checks pass or only cosmetic issues. Script is production-ready.
- REVISE: 1-2 fixable issues (wrong line count, missing trigger). Provide specific correction notes.
- FAIL: Fundamentally broken (wrong destination, harmful content, completely off-topic).

Be lenient — if the script communicates real value in the KSO conversational style, PASS it.

Return ONLY JSON with these fields:
- brief_id (string)
- verdict: "PASS" or "REVISE" or "FAIL"
- checks_passed (number)
- checks_total (number)
- failed_checks (array of strings)
- revision_notes (string or null)
- severity: "none" or "minor" or "major"
"""


def _load_scripts(run_date: date) -> list[dict]:
    """Load today's scripts from file."""
    scripts_file = DATA_DIR / f"scripts_{run_date.isoformat()}.json"
    if not scripts_file.exists():
        return []
    with open(scripts_file) as f:
        data = json.load(f)
    return data.get("scripts", [])


def _load_briefs(run_date: date) -> dict:
    """Load today's briefs indexed by brief_id."""
    briefs_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
    if not briefs_file.exists():
        return {}
    with open(briefs_file) as f:
        data = json.load(f)
    return {b["brief_id"]: b for b in data.get("briefs", []) if "brief_id" in b}


async def _audit_script(script: dict, brief: dict) -> dict:
    """Use Claude Sonnet to audit one script against its brief."""
    from utils.token_tracker import tracked_create

    destination = brief.get("destination", "")
    lines = script.get("script_lines", [])
    length = brief.get("target_length_seconds", 30)
    trigger = brief.get("comment_trigger_phrase", "")
    expected_lines = {15: 4, 30: 5, 45: 6, 60: 7}.get(length, 5)

    prompt = f"""Audit this script for @kso.{destination}.

BRIEF:
- brief_id: {brief.get('brief_id', '')}
- Topic: {brief.get('topic', '')}
- Hook angle: {brief.get('hook_angle', '')}
- Hook text: {brief.get('hook_text', '')}
- Category: {brief.get('content_category', '')}
- Target length: {length}s ({expected_lines} lines)
- Trigger phrase: {trigger}
- Video format: {brief.get('video_format', 'green_screen_text')}
- Deal: {json.dumps(brief.get('deal'), default=str) if brief.get('deal') else 'None'}

SCRIPT:
{json.dumps(lines, indent=2)}

CAPTION: {script.get('caption', '')}
HASHTAGS: {json.dumps(script.get('hashtags', []))}"""

    text, _usage = tracked_create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=[{
            "type": "text",
            "text": AUDIT_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
        agent_name="content_auditor",
        context={"brief_id": brief.get("brief_id", "")},
    )
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    result = json.loads(text)
    return result


async def audit_batch(
    scripts: list[dict], briefs_map: dict
) -> list[dict]:
    """Audit a batch of scripts concurrently."""
    tasks = []
    script_brief_pairs = []

    for script in scripts:
        brief_id = script.get("brief_id", "")
        brief = briefs_map.get(brief_id, {})
        if not brief:
            logger.warning(f"No brief found for {brief_id} — skipping audit")
            continue
        tasks.append(_audit_script(script, brief))
        script_brief_pairs.append((script, brief))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    audit_results = []
    for (script, brief), result in zip(script_brief_pairs, results):
        brief_id = brief.get("brief_id", "?")
        if isinstance(result, Exception):
            logger.error(f"Audit failed for {brief_id}: {result}")
            audit_results.append({
                "brief_id": brief_id,
                "verdict": "FAIL",
                "checks_passed": 0,
                "checks_total": 0,
                "failed_checks": [f"Audit error: {result}"],
                "revision_notes": None,
                "severity": "major",
            })
        else:
            verdict = result.get("verdict", "FAIL")
            passed = result.get("checks_passed", 0)
            total = result.get("checks_total", 0)
            if verdict == "PASS":
                logger.info(f"PASS: {brief_id} ({passed}/{total} checks)")
            elif verdict == "REVISE":
                logger.warning(
                    f"REVISE: {brief_id} — {result.get('revision_notes', '')[:80]}"
                )
            else:
                logger.error(f"FAIL: {brief_id} — {result.get('failed_checks', [])}")
            audit_results.append(result)

    return audit_results


async def run(run_date: date | None = None) -> dict:
    """Run Content Auditor for all scripts.

    Returns:
        dict with "audit_results" (list) and "stats" (summary).
    """
    if run_date is None:
        run_date = date.today()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check: skip if today's audit results already exist
    cache_file = DATA_DIR / f"audit_results_{run_date.isoformat()}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("results"):
            passed = sum(1 for r in cached["results"] if r.get("verdict") == "PASS")
            revise = sum(1 for r in cached["results"] if r.get("verdict") == "REVISE")
            failed = sum(1 for r in cached["results"] if r.get("verdict") == "FAIL")
            logger.info(f"=== Content Auditor CACHED for {run_date}: {passed} PASS, {revise} REVISE, {failed} FAIL ===")
            return {"audit_results": cached["results"], "stats": {"total_audited": len(cached["results"]), "passed": passed, "revise": revise, "failed": failed, "cached": True}}

    logger.info(f"=== Content Auditor starting for {run_date} ===")

    run_id = None
    try:
        run_id = db.log_pipeline_run(run_date, "phase2", "content_auditor")
    except Exception as e:
        logger.warning(f"Failed to log pipeline run: {e}")

    scripts = _load_scripts(run_date)
    briefs_map = _load_briefs(run_date)

    if not scripts:
        logger.error("No scripts found — run Script Writer first")
        return {"audit_results": [], "stats": {"total": 0, "error": "No scripts"}}

    logger.info(f"Auditing {len(scripts)} scripts in batches of {BATCH_SIZE}")

    all_results = []
    errors = []

    # Process in batches
    for i in range(0, len(scripts), BATCH_SIZE):
        batch = scripts[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(scripts) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"Audit batch {batch_num}/{total_batches} ({len(batch)} scripts)...")

        try:
            results = await audit_batch(batch, briefs_map)
            all_results.extend(results)
        except Exception as e:
            logger.error(f"Audit batch {batch_num} failed: {e}")
            errors.append({"batch": batch_num, "error": str(e)})

    # Save results
    output_file = DATA_DIR / f"audit_results_{run_date.isoformat()}.json"

    passed = [r for r in all_results if r.get("verdict") == "PASS"]
    revise = [r for r in all_results if r.get("verdict") == "REVISE"]
    failed = [r for r in all_results if r.get("verdict") == "FAIL"]

    with open(output_file, "w") as f:
        json.dump(
            {
                "date": run_date.isoformat(),
                "total_audited": len(all_results),
                "passed": len(passed),
                "revise": len(revise),
                "failed": len(failed),
                "results": all_results,
            },
            f,
            indent=2,
        )
    logger.info(f"Saved {len(all_results)} audit results to {output_file}")

    # Save to Supabase
    try:
        db.save_audit_results(all_results)
    except Exception as e:
        logger.warning(f"Failed to save audit results to Supabase: {e}")

    stats = {
        "total_audited": len(all_results),
        "passed": len(passed),
        "revise": len(revise),
        "failed": len(failed),
        "pass_rate": f"{len(passed)/len(all_results)*100:.1f}%" if all_results else "0%",
        "errors": len(errors),
    }

    if run_id:
        try:
            db.update_pipeline_run(
                run_id,
                status="completed" if not errors else "completed_with_errors",
                audits_passed=len(passed),
                audits_revise=len(revise),
                audits_failed=len(failed),
                errors=errors,
            )
        except Exception as e:
            logger.warning(f"Failed to update pipeline run: {e}")

    logger.info(
        f"=== Content Auditor complete: {len(passed)} PASS, {len(revise)} REVISE, "
        f"{len(failed)} FAIL ({stats['pass_rate']} pass rate) ==="
    )

    return {"audit_results": all_results, "stats": stats}


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result["stats"], indent=2))
