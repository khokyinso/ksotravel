"""Agent 5: Script Writer

Writes 96 TikTok/Reels scripts in parallel batches of 12.
Each script includes comment CTA with trigger phrase and affiliate CTA with promo code.

Model: Claude Sonnet 4.6
Schedule: 6:00 AM EST — parallel batches of 12
Output: data/scripts_{date}.json
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

BATCH_SIZE = 12  # Process 12 scripts in parallel

CTA_TEMPLATES = {
    "A": 'Comment {phrase} and I\'ll send you the full guide',
    "B": 'Drop {phrase} below for the complete breakdown',
    "C": 'Type {phrase} in comments — I\'ll DM you the link',
    "D": 'Comment {phrase} for my free {destination} guide',
}

SYSTEM_PROMPT = """You write TikTok/Reels scripts for @insearchofkso travel channels.
Voice: confident, specific, direct, urgent. First-person preferred.

RULES:
- Every line ≤ 8 words
- Always include real USD prices
- Always include real product/place names
- Always include promo code KSOTRAVEL
- NEVER start: "If you are traveling to..."
- NEVER use vague language ("some", "many", "often")
- Second-to-last line = comment CTA with provided trigger phrase
- Last line = affiliate platform + KSOTRAVEL

PROVEN HOOK STARTERS:
"Stop wasting money on [X] in [destination]"
"Most tourists make this mistake in [destination]"
"Don't visit [destination] without knowing this"
"I saved $X by doing this instead"
"Never book [X] before checking [Y]"
"[Destination] locals never tell tourists this"

DESTINATION NOTES:
- China: mention visa type / VPN / payment when relevant
- Turkey: USD prices only — never Turkish Lira
- Poland: emphasize budget angle (Europe's best value)
- France: subvert Parisian clichés ("Everyone goes to Paris, go here instead")
"""


def _get_cta_winner() -> str:
    """Get current CTA template winner from performance weights, default to A."""
    try:
        from utils import supabase_client as db
        # Check all destinations for a cta_winner weight
        weights = db.get_performance_weights("global", metric_type="cta_winner")
        if weights:
            # Return the key with the highest weight
            return max(weights, key=weights.get)
    except Exception:
        pass
    return "A"


def _load_briefs(run_date: date) -> list[dict]:
    """Load today's briefs from file."""
    briefs_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
    if not briefs_file.exists():
        return []
    with open(briefs_file) as f:
        data = json.load(f)
    return data.get("briefs", [])


async def _write_script(brief: dict, cta_winner: str) -> dict:
    """Use Claude Sonnet to write one script from a brief."""
    from utils.token_tracker import tracked_create

    destination = brief.get("destination", "")
    length = brief.get("target_length_seconds", 30)
    trigger = brief.get("comment_trigger_phrase", "INFO")
    video_format = brief.get("video_format", "green_screen_text")

    # Determine line count
    if length == 15:
        line_count = 5
    elif length == 30:
        line_count = 7
    else:
        line_count = 10

    # Build CTA line
    cta_template = CTA_TEMPLATES.get(cta_winner, CTA_TEMPLATES["A"])
    cta_line = cta_template.format(phrase=trigger, destination=destination)

    # Build deal info
    deal = brief.get("deal")
    deal_text = ""
    if deal:
        deal_text = f"""
DEAL TO FEATURE:
- Platform: {deal.get('platform', 'N/A')}
- Product: {deal.get('product', 'N/A')}
- Price: ${deal.get('price_usd', 'N/A')}
- Promo code: KSOTRAVEL"""

    prompt = f"""Write a {length}-second TikTok/Reels script for @kso.{destination}.

BRIEF:
- Topic: {brief.get('topic', '')}
- Hook angle: {brief.get('hook_angle', '')}
- Hook text: {brief.get('hook_text', '')}
- Category: {brief.get('content_category', '')}
- Video format: {video_format}
- Trigger phrase: {trigger}
{deal_text}

SCRIPT REQUIREMENTS:
- Exactly {line_count} lines
- Line 1: Hook (use or adapt the hook_text above, ≤8 words)
- {"Lines 2-3: Tip with specific detail" if length == 15 else "Lines 2-" + str(line_count - 2) + ": Tips, context, details"}
- Line {line_count - 1}: "{cta_line}"
- Line {line_count}: Platform name + "use code KSOTRAVEL"
- Every line ≤ 8 words
- Include real USD prices
- Include real place/product names

VIDEO FORMAT NOTES ({video_format}):
{"- Text overlay on stock footage, each line appears as a card" if video_format == "green_screen_text" else ""}
{"- POV walking perspective, describe what viewer sees" if video_format == "pov_walking" else ""}
{"- Side-by-side comparison, alternate between two options" if video_format == "split_screen" else ""}
{"- Photo slideshow with voiceover narration style" if video_format == "photo_slideshow" else ""}
{"- Part of a series, hint at next part" if video_format == "series_part" else ""}
{"- Reaction to common tourist mistake or viral clip" if video_format == "stitch_reaction" else ""}
{"- Map zoom-in transition to specific location" if video_format == "map_zoom" else ""}
{"- Before/after or expectation vs reality reveal" if video_format == "before_after" else ""}
{"- Countdown listicle (5, 4, 3, 2, 1)" if video_format == "countdown_list" else ""}
{"- Personal story with text captions" if video_format == "storytime" else ""}

Also generate:
- caption: ≤150 chars before hashtags, compelling, includes trigger phrase mention
- hashtags: 4-6 relevant hashtags
- geotag: specific location name

Return ONLY JSON:
{{
  "brief_id": "{brief.get('brief_id', '')}",
  "script_lines": ["line1", "line2", ...],
  "caption": "...",
  "hashtags": ["#tag1", "#tag2", ...],
  "affiliate_url": "{deal.get('url', '') if deal else ''}",
  "geotag": "City, Country",
  "target_length_seconds": {length},
  "video_format": "{video_format}"
}}"""

    text, _usage = tracked_create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
        agent_name="script_writer",
        context={"brief_id": brief.get("brief_id", "")},
    )
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    script = json.loads(text)
    return script


def _validate_script(script: dict, brief: dict) -> dict:
    """Validate script meets all requirements."""
    lines = script.get("script_lines", [])
    length = brief.get("target_length_seconds", 30)
    trigger = brief.get("comment_trigger_phrase", "")

    expected_lines = {15: 5, 30: 7, 45: 10, 60: 10}.get(length, 7)

    issues = []

    # Check line count
    if len(lines) != expected_lines:
        issues.append(f"Expected {expected_lines} lines, got {len(lines)}")

    # Check line length (≤8 words)
    for i, line in enumerate(lines):
        word_count = len(line.split())
        if word_count > 10:  # Allow slight flexibility
            issues.append(f"Line {i+1} has {word_count} words (max ~8)")

    # Check trigger phrase present
    trigger_found = any(trigger.lower() in line.lower() for line in lines)
    if not trigger_found and trigger:
        issues.append(f"Trigger phrase '{trigger}' not found in script")

    # Check KSOTRAVEL present
    kso_found = any("KSOTRAVEL" in line.upper() for line in lines)
    if not kso_found:
        issues.append("KSOTRAVEL promo code not found")

    script["validation_issues"] = issues
    script["is_valid"] = len(issues) == 0
    script["brief_id"] = brief.get("brief_id", "")

    return script


async def write_batch(briefs: list[dict], cta_winner: str) -> list[dict]:
    """Write scripts for a batch of briefs concurrently."""
    tasks = [_write_script(b, cta_winner) for b in briefs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    scripts = []
    for brief, result in zip(briefs, results):
        if isinstance(result, Exception):
            logger.error(f"Script Writer failed for {brief.get('brief_id', '?')}: {result}")
        else:
            script = _validate_script(result, brief)
            scripts.append(script)
            if script["is_valid"]:
                logger.info(f"Script OK: {brief['brief_id']}")
            else:
                logger.warning(
                    f"Script issues for {brief['brief_id']}: {script['validation_issues']}"
                )

    return scripts


async def run(run_date: date | None = None) -> dict:
    """Run Script Writer for all briefs.

    Returns:
        dict with "scripts" (list) and "stats" (summary).
    """
    if run_date is None:
        run_date = date.today()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check: skip if today's scripts already exist
    cache_file = DATA_DIR / f"scripts_{run_date.isoformat()}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("scripts"):
            logger.info(f"=== Script Writer CACHED for {run_date}: {len(cached['scripts'])} scripts ===")
            return {"scripts": cached["scripts"], "stats": {"total_scripts": len(cached["scripts"]), "valid": sum(1 for s in cached["scripts"] if s.get("is_valid")), "cached": True}}

    logger.info(f"=== Script Writer starting for {run_date} ===")

    run_id = None
    try:
        run_id = db.log_pipeline_run(run_date, "phase2", "script_writer")
    except Exception as e:
        logger.warning(f"Failed to log pipeline run: {e}")

    briefs = _load_briefs(run_date)
    if not briefs:
        logger.error("No briefs found — run Phase 1 first")
        return {"scripts": [], "stats": {"total": 0, "error": "No briefs"}}

    cta_winner = _get_cta_winner()
    logger.info(f"CTA template winner: {cta_winner}")
    logger.info(f"Processing {len(briefs)} briefs in batches of {BATCH_SIZE}")

    all_scripts = []
    errors = []

    # Process in batches
    for i in range(0, len(briefs), BATCH_SIZE):
        batch = briefs[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(briefs) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"Batch {batch_num}/{total_batches} ({len(batch)} scripts)...")

        try:
            scripts = await write_batch(batch, cta_winner)
            all_scripts.extend(scripts)
        except Exception as e:
            logger.error(f"Batch {batch_num} failed: {e}")
            errors.append({"batch": batch_num, "error": str(e)})

    # Save to file
    output_file = DATA_DIR / f"scripts_{run_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump(
            {
                "date": run_date.isoformat(),
                "total_scripts": len(all_scripts),
                "cta_winner": cta_winner,
                "scripts": all_scripts,
            },
            f,
            indent=2,
        )
    logger.info(f"Saved {len(all_scripts)} scripts to {output_file}")

    # Save to Supabase
    try:
        db.save_scripts(all_scripts)
    except Exception as e:
        logger.warning(f"Failed to save scripts to Supabase: {e}")

    valid_count = sum(1 for s in all_scripts if s.get("is_valid"))
    stats = {
        "total_scripts": len(all_scripts),
        "valid": valid_count,
        "with_issues": len(all_scripts) - valid_count,
        "errors": len(errors),
        "cta_winner": cta_winner,
    }

    if run_id:
        try:
            db.update_pipeline_run(
                run_id,
                status="completed" if not errors else "completed_with_errors",
                scripts_generated=len(all_scripts),
                errors=errors,
            )
        except Exception as e:
            logger.warning(f"Failed to update pipeline run: {e}")

    logger.info(
        f"=== Script Writer complete: {valid_count}/{len(all_scripts)} valid, "
        f"{len(errors)} batch errors ==="
    )

    return {"scripts": all_scripts, "stats": stats}


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result["stats"], indent=2))
