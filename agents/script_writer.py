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

SYSTEM_PROMPT = """You write TikTok/Reels scripts for @kso.travel channels.

VOICE & TONE:
You are a helpful friend who has personally traveled to every destination. You speak conversationally,
in second person ("If you're planning to...") mixed with first person experience ("My step count was...").
You give real, specific, practical advice — not generic travel guide fluff.

SCRIPT STRUCTURE (this order matters):
1. TITLE: Just the series title, nothing else. e.g. "Japan Travel Tip #33"
2. HOOK: Relatable "If you're..." statement. One sentence only.
3. KEY FACTS: 2-3 short punchy blocks. One idea per block. Numbers get their own block.
4. CTA: "If this is helpful, make sure to follow for more tips."

WRITING RULES:
- Each script_line = MAX 15 words. This is 1-2 lines on a phone screen.
- ONE idea per block. If you have two ideas, make two blocks.
- Key numbers/dates deserve their own block for impact.
- Be conversational — "you", "your", contractions ("don't", "you're")
- Include real USD prices, real dates, real product/place names
- NEVER use vague language ("some", "many", "often", "various")
- 15s video = 4-5 blocks. 30s video = 5-6 blocks. 45-60s video = 6-8 blocks.

EXAMPLES OF CORRECT SCRIPT_LINES:
["Japan Travel Tip #33",
 "If you're planning to come to Japan in 2024, make sure to avoid Golden Week.",
 "This year it's 4/29-5/5.",
 "Everybody in Japan's off. Every line will be wayyy longer.",
 "If you're visiting Japan this year, follow for more tips."]

["Japan Travel Tips #9",
 "If you want to go to Shibuya Sky for sunset, make sure to go 1.5 hours before.",
 "Pro tip — there's a sky bar so you can enjoy a drink while waiting.",
 "Buy your tickets online so you don't have to go through long queues.",
 "If you are traveling to Japan, my profile will keep providing tips."]

BAD — TOO LONG (never do this):
"The 7-day JR Pass costs $317 USD right now. That sounds like a deal until you actually map out your itinerary and realize you might not even use $317 worth of trains."

PROVEN HOOK OPENERS (use these patterns):
"If you're planning to come to {destination} in 2024..."
"If you're traveling to {destination} and thinking about getting a {X} — don't."
"If you are visiting {destination}, make sure to {X}"
"Don't buy a {X} if you're just going to {destination} for a week!"
"{Destination} Travel Tip #{N}: Make sure to {X}"
"Day {N} of helping you plan your trip to {destination}"

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

    # Determine block count (matching system prompt rules)
    if length == 15:
        line_count = 4
    elif length == 30:
        line_count = 5
    elif length == 45:
        line_count = 6
    else:
        line_count = 7

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

    # Get series number from brief
    series_num = brief.get("series_number", "")
    series_title = f"{destination.title()} Travel Tip #{series_num}" if series_num else ""

    prompt = f"""Write a {length}-second TikTok/Reels script for @kso.{destination}.

BRIEF:
- Topic: {brief.get('topic', '')}
- Hook angle: {brief.get('hook_angle', '')}
- Hook text: {brief.get('hook_text', '')}
- Category: {brief.get('content_category', '')}
- Video format: {video_format}
- Trigger phrase: {trigger}
{"- Series title: " + series_title if series_title else ""}
{deal_text}

SCRIPT REQUIREMENTS:
- Write exactly {line_count} script_lines
- Each line is MAX 15 words. One idea per line. Short and punchy.
- Line 1: Series title only (e.g. "{series_title}" or "{destination.title()} Travel Tip")
- Line 2: Relatable hook — "If you're planning to..." or "If you're traveling to..."
- Middle lines: Key facts, tips, prices. One fact per line. Numbers get their own line.
- Last line: Soft CTA — "Follow for more {destination.title()} tips" or "Comment {trigger} for the full guide"

CRITICAL: Each script_line must be MAX 15 words. Not 20, not 25 — fifteen or fewer.
Example: "If you're planning to come to Japan in 2024, make sure to avoid visiting during Japan's Golden Week. This year it's 4/29-5/5. This is a week where everybody in Japan's off. Every line in Japan will be wayyy longer."

Also generate:
- caption: ≤150 chars before hashtags, compelling, conversational
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

    expected_lines = {15: 4, 30: 5, 45: 6, 60: 7}.get(length, 5)

    issues = []

    # Check line count (allow ±2 flexibility)
    if abs(len(lines) - expected_lines) > 2:
        issues.append(f"Expected ~{expected_lines} lines, got {len(lines)}")

    # Check block length (≤15 words — short punchy blocks matching KSO style)
    for i, line in enumerate(lines):
        word_count = len(line.split())
        if word_count > 15:
            issues.append(f"Block {i+1} has {word_count} words (max 15)")

    # Check trigger phrase present
    trigger_found = any(trigger.lower() in line.lower() for line in lines)
    if not trigger_found and trigger:
        issues.append(f"Trigger phrase '{trigger}' not found in script")

    # Check KSOTRAVEL present (only if brief has a deal)
    has_deal = brief.get("deal") is not None
    if has_deal:
        kso_found = any("KSOTRAVEL" in line.upper() for line in lines)
        if not kso_found:
            issues.append("KSOTRAVEL promo code not found (brief has deal)")

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
