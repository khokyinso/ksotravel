"""Agent 2: Deal Harvester

Scores and ranks 10+ affiliate deals per destination per day across 5 platforms.
Uses Claude Haiku to evaluate deal quality and assign scores.

Model: Claude Haiku 4.5
Schedule: 5:00 AM EST (parallel with Agent 1)
Output: data/deals_{date}.json
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import anthropic
import httpx
from dotenv import load_dotenv
from loguru import logger

from utils import supabase_client as db
from config.constants import (
    DESTINATIONS, PLATFORM_PRIORITY, DEAL_CATEGORIES, PLATFORM_COMMISSIONS,
)

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

DEAL_HARVESTER_SYSTEM_PROMPT = """You are the Deal Harvester for @insearchofkso travel channels.
Generate exactly 10 realistic, high-quality affiliate deals per destination.
Each deal must be a real product/tour/experience that exists on affiliate platforms.

Deal categories: ["transport", "attraction", "food_tour", "accommodation", "experience", "day_trip", "guided_tour"]

Commission rates by platform:
- Klook: 5-8%, 30-day cookie
- GetYourGuide (gyg): 8%, 30-day cookie
- Viator: 8%, 30-day cookie
- Booking.com: 4-6%, session cookie only
- Expedia: 2-6%, 7-day cookie

RULES:
- All prices in USD
- Use real product names that exist on these platforms
- Mix categories — variety is key
- Higher-commission platforms should appear more often
- Include at least 2 high-urgency deals (limited availability, seasonal)
- Generate realistic affiliate URLs (placeholder format: https://{platform}.com/aff/{product_slug})

Scoring formula:
deal_score = (commission_rate/100 * 0.4) + (review_score * 0.3) + (booking_velocity * 0.2) + (urgency_flag * 0.1)
- review_score: 0.0-1.0 (based on your assessment of likely reviews)
- booking_velocity: 0.0-1.0 (how fast this sells)
- urgency_flag: 1.0 if limited/seasonal, 0.0 if not

Return ONLY a JSON array of 10 objects with these fields:
- platform (string)
- product_name (string): real product name
- affiliate_url (string): placeholder affiliate URL
- price_usd (number): price in USD
- commission_pct (number): commission percentage
- deal_score (number): computed score 0.0-1.0
- urgency (string or null): "limited availability", "seasonal", "ending soon", or null
- category (string): one of the deal categories
- review_score (number): 0.0-1.0
- booking_velocity (number): 0.0-1.0

Return ONLY the JSON array, no other text."""


def _compute_deal_score(deal: dict) -> float:
    """Compute deal score using the formula from docs.

    deal_score = (commission_rate * 0.4) + (review_score * 0.3)
               + (booking_velocity * 0.2) + (urgency_flag * 0.1)
    """
    commission = deal.get("commission_pct", 5) / 100.0
    review = deal.get("review_score", 0.7)
    velocity = deal.get("booking_velocity", 0.5)
    urgency = 1.0 if deal.get("urgency") else 0.0

    score = (commission * 0.4) + (review * 0.3) + (velocity * 0.2) + (urgency * 0.1)
    return round(min(score, 1.0), 4)


async def _fetch_platform_deals(
    destination: str, platform: str
) -> list[dict]:
    """Fetch deals from an affiliate platform API.

    In Phase 1, this uses Claude AI to generate realistic deal data
    based on current market knowledge, since affiliate API integrations
    come in later phases.
    """
    # Placeholder: real API integrations come in Phase 8 (Agent 13)
    # For now, we generate representative deals via AI
    return []


def _generate_deals_with_ai(
    destination: str, platforms: list[str], run_date: date
) -> list[dict]:
    """Use Claude Haiku to generate scored deals for a destination."""
    from utils.token_tracker import tracked_create

    # Get performance weights for CTR bonus (Agent 14 feedback)
    try:
        perf_weights = db.get_performance_weights(destination)
    except Exception:
        perf_weights = {}

    ctr_bonus_note = ""
    if perf_weights:
        ctr_bonus_note = f"\nHistorical CTR weights (add +0.15 bonus to these categories): {json.dumps(perf_weights)}"

    dest_specific = ""
    if destination == "turkey":
        dest_specific = "TURKEY: All prices in USD only, never Turkish Lira."
    elif destination == "china":
        dest_specific = "CHINA: Include at least 1 visa-related or practical entry product."

    prompt = f"""Destination: {destination.title()}
Today's date: {run_date.isoformat()}
Priority platforms (in order): {json.dumps(platforms)}
{ctr_bonus_note}
{f"DESTINATION RULE: {dest_specific}" if dest_specific else ""}"""

    text, _usage = tracked_create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        system=[{
            "type": "text",
            "text": DEAL_HARVESTER_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
        agent_name="deal_harvester",
        context={"destination": destination},
    )
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        deals = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response for {destination}: {e}")
        return []

    # Validate, recompute scores, add destination
    validated = []
    for d in deals:
        if not isinstance(d, dict):
            continue
        d["destination"] = destination
        # Recompute score to ensure consistency
        d["deal_score"] = _compute_deal_score(d)
        # Apply CTR bonus from Agent 14
        if perf_weights:
            cat = d.get("category", "")
            if cat in perf_weights:
                d["deal_score"] = min(d["deal_score"] + 0.15, 1.0)
        if d.get("category") not in DEAL_CATEGORIES:
            d["category"] = "experience"
        validated.append(d)

    # Sort by score descending
    validated.sort(key=lambda x: x["deal_score"], reverse=True)
    return validated


async def harvest_destination(destination: str, run_date: date) -> list[dict]:
    """Harvest deals for one destination."""
    logger.info(f"Harvesting deals for {destination}...")

    platforms = PLATFORM_PRIORITY.get(destination, ["gyg", "viator", "klook"])
    deals = _generate_deals_with_ai(destination, platforms, run_date)

    logger.info(f"Generated {len(deals)} deals for {destination}")
    return deals


async def run(run_date: date | None = None) -> dict:
    """Run Deal Harvester for all 12 destinations.

    Returns:
        dict with "deals" (list) and "stats" (summary).
    """
    if run_date is None:
        run_date = date.today()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check: skip if today's deals already exist
    cache_file = DATA_DIR / f"deals_{run_date.isoformat()}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("deals"):
            logger.info(f"=== Deal Harvester CACHED for {run_date}: {len(cached['deals'])} deals ===")
            return {"deals": cached["deals"], "stats": {"total_deals": len(cached["deals"]), "cached": True}}

    logger.info(f"=== Deal Harvester starting for {run_date} ===")

    run_id = None
    try:
        run_id = db.log_pipeline_run(run_date, "phase1", "deal_harvester")
    except Exception as e:
        logger.warning(f"Failed to log pipeline run: {e}")

    all_deals = []
    errors = []

    # Run all destinations concurrently
    tasks = [harvest_destination(dest, run_date) for dest in DESTINATIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for dest, result in zip(DESTINATIONS, results):
        if isinstance(result, Exception):
            logger.error(f"Deal Harvester failed for {dest}: {result}")
            errors.append({"destination": dest, "error": str(result)})
        else:
            all_deals.extend(result)

    # Save to file
    output_file = DATA_DIR / f"deals_{run_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump({"date": run_date.isoformat(), "deals": all_deals}, f, indent=2)
    logger.info(f"Saved {len(all_deals)} deals to {output_file}")

    # Save to Supabase
    try:
        db.save_deals(all_deals, run_date)
    except Exception as e:
        logger.warning(f"Failed to save deals to Supabase: {e}")

    if run_id:
        try:
            db.update_pipeline_run(
                run_id,
                status="completed" if not errors else "completed_with_errors",
                briefs_generated=len(all_deals),
                errors=errors,
            )
        except Exception as e:
            logger.warning(f"Failed to update pipeline run: {e}")

    stats = {
        "total_deals": len(all_deals),
        "per_destination": {
            dest: len([d for d in all_deals if d.get("destination") == dest])
            for dest in DESTINATIONS
        },
        "avg_score": round(
            sum(d.get("deal_score", 0) for d in all_deals) / max(len(all_deals), 1), 4
        ),
        "errors": len(errors),
    }
    logger.info(f"=== Deal Harvester complete: {stats['total_deals']} deals, avg score {stats['avg_score']} ===")

    return {"deals": all_deals, "stats": stats}


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result["stats"], indent=2))
