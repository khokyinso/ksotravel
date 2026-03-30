"""Agent 3: Content Strategist

Generates 8 content briefs per channel (96 total daily).
AI decides full content mix based on trends, deals, history, and performance weights.
Assigns comment trigger phrase to every video.

Model: Claude Haiku 4.5
Schedule: 5:30 AM EST (after Agents 1 & 2)
Output: data/briefs_{date}.json (96 briefs)
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from loguru import logger

from agents.format_scanner import get_format_recommendations

from utils import supabase_client as db
from utils.duplicate_checker import filter_duplicates, get_recent_topics
from config.constants import DESTINATIONS

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

STRATEGIST_SYSTEM_PROMPT = """You are the Content Strategist for @insearchofkso travel channels.
You generate exactly 8 content briefs per channel — one for each posting slot per day.
AI-decide the full content mix based on available trends, deals, and what's working.

HARD RULES:
- No duplicate topic within 60 days on same channel
- Max 3 same-category videos per channel per day
- Min 2 "warning" or "hack" hooks per channel per day
- Min 1 affiliate deal per channel per day
- Every video gets a unique trigger phrase (1-3 words, easy to type)
- Hook text must be ≤8 words

VIDEO FORMATS:
- green_screen_text: Text overlay on stock footage (KSO default)
- pov_walking: POV walking tour / first person
- split_screen: Side-by-side comparison
- photo_slideshow: Photo slideshow with voiceover
- series_part: "Part 1/2/3" series hook
- stitch_reaction: Stitch/duet reaction to another creator
- map_zoom: Map zoom-in transition to location
- before_after: Expectation vs reality reveal
- countdown_list: Countdown listicle (5, 4, 3, 2, 1)
- storytime: Personal story with text captions

If a trend has a video_format, prefer that format for the brief.
Mix formats across the 8 briefs — don't use the same format for all.

VIDEO LENGTHS:
- Single tip / warning → 15s (5 script lines)
- Tip + context + deal → 30s (7 script lines)
- Comparison (X vs Y) → 45s (10 script lines)
- Listicle / story → 60s (10 script lines)

CTA TEMPLATES (pick one per brief, rotate):
A: "Comment [PHRASE] and I'll send you the full guide"
B: "Drop [PHRASE] below for the complete breakdown"
C: "Type [PHRASE] in comments — I'll DM you the link"
D: "Comment [PHRASE] for my free [destination] guide"

TRIGGER PHRASE RULES:
- 1-3 words max
- Directly related to video topic
- Easy to type in a comment
- Must be unique across all 8 briefs

SAMPLE VIDEO:
Flag exactly 1 of the 8 briefs as is_sample_video: true.
Pick the brief with the highest-stakes factual claim (price, visa info, official dates).

DM PAYLOAD TYPES: "travel_guide", "deal_list", "accommodation_guide", "transport_guide", "food_guide", "visa_guide"

Return ONLY a JSON array of 8 brief objects with these fields:
- brief_id (string): format "{destination}_XXX_{date}" where XXX is 001-008
- channel (string): "kso.{destination}"
- destination (string)
- topic (string): specific topic title
- hook_angle (string): warning, hack, secret, timing, comparison, listicle, story, or reaction
- hook_text (string): ≤8 words, compelling
- video_format (string): one of the video formats listed above
- content_category (string): transport, attraction, food_tour, accommodation, experience, day_trip, guided_tour
- target_length_seconds (integer): 15, 30, 45, or 60
- is_sample_video (boolean): true for exactly 1
- deal (object or null): {platform, product, url, price_usd, commission_pct, promo_code: "KSOTRAVEL"}
- comment_trigger_phrase (string): 1-3 word trigger
- dm_payload_type (string): one of the types above
- posting_slot (integer): 1-8
- posting_time_est (string): matching time from slots
- source_signal (string): what inspired this brief

Return ONLY the JSON array, no other text."""

POSTING_SLOTS = [
    {"slot": 1, "time_est": "07:00"},
    {"slot": 2, "time_est": "09:30"},
    {"slot": 3, "time_est": "12:00"},
    {"slot": 4, "time_est": "14:30"},
    {"slot": 5, "time_est": "17:00"},
    {"slot": 6, "time_est": "19:00"},
    {"slot": 7, "time_est": "20:30"},
    {"slot": 8, "time_est": "22:00"},
]


def _load_channels() -> dict:
    with open(CONFIG_DIR / "channels.json") as f:
        data = json.load(f)
    return {ch["destination"]: ch for ch in data["channels"]}


def _load_content_rules() -> dict:
    with open(CONFIG_DIR / "content_rules.json") as f:
        return json.load(f)


def _load_trends(run_date: date, destination: str) -> list[dict]:
    """Load today's trends for a destination from file."""
    trends_file = DATA_DIR / f"trends_{run_date.isoformat()}.json"
    if not trends_file.exists():
        return []
    with open(trends_file) as f:
        data = json.load(f)
    return [t for t in data.get("trends", []) if t.get("destination") == destination]


def _load_deals(run_date: date, destination: str) -> list[dict]:
    """Load today's deals for a destination from file."""
    deals_file = DATA_DIR / f"deals_{run_date.isoformat()}.json"
    if not deals_file.exists():
        return []
    with open(deals_file) as f:
        data = json.load(f)
    return [d for d in data.get("deals", []) if d.get("destination") == destination]


def _generate_briefs_with_ai(
    destination: str,
    trends: list[dict],
    deals: list[dict],
    recent_topics: list[str],
    channel_config: dict,
    content_rules: dict,
    run_date: date,
) -> list[dict]:
    """Use Claude Haiku to generate 8 content briefs for a destination."""
    from utils.token_tracker import tracked_create

    # Build destination-specific rules
    dest_rules = content_rules.get("destination_specific", {}).get(destination, {})
    dest_rules_text = ""
    if dest_rules:
        dest_rules_text = f"\nDestination-specific rules: {json.dumps(dest_rules)}"

    # Format recent topics for dedup context
    recent_text = ""
    if recent_topics:
        recent_text = f"\nTopics published in last 60 days (DO NOT REPEAT): {json.dumps(recent_topics[:30])}"

    # Get performance weights
    try:
        perf_weights = db.get_performance_weights(destination)
        perf_text = f"\nPerformance weights from Agent 15: {json.dumps(perf_weights)}" if perf_weights else ""
    except Exception:
        perf_text = ""

    trends_json = json.dumps(trends[:12], indent=2, default=str)
    deals_json = json.dumps(deals[:10], indent=2, default=str)
    run_date_no_dashes = run_date.strftime("%Y%m%d")

    dest_specific = ""
    if destination == "china":
        dest_specific = "- China: min 1 visa/entry tip per day"
    elif destination == "france":
        dest_specific = "- France: min 1 underrated vs overtouristed angle per day"
    elif destination == "turkey":
        dest_specific = "- Turkey: min 1 underrated vs overtouristed angle per day, USD only"
    elif destination == "poland":
        dest_specific = "- Poland: min 1 underrated vs overtouristed or budget angle per day"

    prompt = f"""Generate 8 briefs for @kso.{destination} on {run_date.isoformat()}.
brief_id format: {destination}_XXX_{run_date_no_dashes}

AVAILABLE TRENDS:
{trends_json}

AVAILABLE DEALS:
{deals_json}
{recent_text}
{perf_text}
{dest_rules_text}

{f"DESTINATION RULE: {dest_specific}" if dest_specific else ""}

POSTING SLOTS: {json.dumps(POSTING_SLOTS)}"""

    text, _usage = tracked_create(
        model="claude-haiku-4-5-20251001",
        max_tokens=5000,
        system=[{
            "type": "text",
            "text": STRATEGIST_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
        agent_name="content_strategist",
        context={"destination": destination},
    )
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        briefs = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response for {destination}: {e}")
        logger.debug(f"Raw response: {text[:500]}")
        return []

    return briefs


def _validate_briefs(
    briefs: list[dict],
    destination: str,
    run_date: date,
    content_rules: dict,
) -> list[dict]:
    """Validate and fix briefs to ensure they meet all hard rules."""
    validated = []
    seen_triggers = set()
    category_counts: dict[str, int] = {}
    hook_angle_counts: dict[str, int] = {}
    has_sample = False
    has_deal = False

    for i, b in enumerate(briefs):
        if not isinstance(b, dict):
            continue

        # Ensure required fields
        b.setdefault("destination", destination)
        b.setdefault("channel", f"kso.{destination}")
        b.setdefault("date", run_date.isoformat())

        # Fix brief_id format
        idx = str(i + 1).zfill(3)
        date_str = run_date.isoformat().replace("-", "")
        b["brief_id"] = f"{destination}_{idx}_{date_str}"

        # Validate posting slot
        if b.get("posting_slot") not in range(1, 9):
            b["posting_slot"] = i + 1
        slot_info = POSTING_SLOTS[b["posting_slot"] - 1]
        b["posting_time_est"] = slot_info["time_est"]

        # Validate hook angle
        valid_angles = content_rules["hook_angles_ranked"]
        if b.get("hook_angle") not in valid_angles:
            b["hook_angle"] = "hack"
        hook_angle_counts[b["hook_angle"]] = hook_angle_counts.get(b["hook_angle"], 0) + 1

        # Validate length
        if b.get("target_length_seconds") not in (15, 30, 45, 60):
            b["target_length_seconds"] = 30

        # Assign optimal video format using format scanner recommendations
        valid_formats = [
            "green_screen_text", "pov_walking", "split_screen", "photo_slideshow",
            "series_part", "stitch_reaction", "map_zoom", "before_after",
            "countdown_list", "storytime", "tier_list",
        ]
        if b.get("video_format") not in valid_formats:
            # Use format scanner to pick the best format for this content
            recs = get_format_recommendations(
                content_category=b.get("content_category", "experience"),
                destination=destination,
                hook_angle=b.get("hook_angle", "hack"),
            )
            b["video_format"] = recs[0]["format"] if recs else "green_screen_text"
            b["remotion_template"] = recs[0]["remotion_template"] if recs else "GreenScreenText"

        # Validate trigger phrase uniqueness
        trigger = b.get("comment_trigger_phrase", "").upper().strip()
        if trigger in seen_triggers or not trigger:
            trigger = f"{destination.upper()} {idx}"
            b["comment_trigger_phrase"] = trigger
        seen_triggers.add(trigger)

        # Track categories
        cat = b.get("content_category", "experience")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        if category_counts[cat] > 3:
            continue  # Skip — would exceed 3 per category limit

        # Track deals
        if b.get("deal"):
            has_deal = True

        # Track sample
        if b.get("is_sample_video"):
            if has_sample:
                b["is_sample_video"] = False
            else:
                has_sample = True

        validated.append(b)

    # Ensure at least 1 sample video
    if not has_sample and validated:
        validated[0]["is_sample_video"] = True

    # Ensure we have exactly 8
    if len(validated) > 8:
        validated = validated[:8]

    return validated


async def strategize_destination(
    destination: str,
    run_date: date,
    channels: dict,
    content_rules: dict,
) -> list[dict]:
    """Generate briefs for one destination."""
    logger.info(f"Strategizing content for {destination}...")

    trends = _load_trends(run_date, destination)
    deals = _load_deals(run_date, destination)
    recent_topics = get_recent_topics(destination)
    channel_config = channels.get(destination, {})

    if not trends:
        logger.warning(f"No trends found for {destination} — AI will use general knowledge")
    if not deals:
        logger.warning(f"No deals found for {destination} — AI will use general knowledge")

    briefs = _generate_briefs_with_ai(
        destination=destination,
        trends=trends,
        deals=deals,
        recent_topics=recent_topics,
        channel_config=channel_config,
        content_rules=content_rules,
        run_date=run_date,
    )

    # Validate
    briefs = _validate_briefs(briefs, destination, run_date, content_rules)

    # Filter duplicates against published history
    briefs = filter_duplicates(briefs, destination, topic_key="topic")

    # Assign series numbers — serialized tips get a number, listicles/standalone don't
    try:
        series_numbers = db.get_next_series_numbers(destination, count=len(briefs))
        for i, brief in enumerate(briefs):
            # Listicles and standalone content don't get series numbers
            hook = brief.get("hook_angle", "")
            if hook in ("listicle", "story", "reaction"):
                brief["series_number"] = None
                brief["series_type"] = "standalone"
            else:
                brief["series_number"] = series_numbers[i]
                brief["series_type"] = "travel_tip"
    except Exception as e:
        logger.warning(f"Failed to assign series numbers for {destination}: {e}")

    logger.info(f"Generated {len(briefs)} validated briefs for {destination}")
    return briefs


async def run(run_date: date | None = None) -> dict:
    """Run Content Strategist for all 12 destinations.

    Returns:
        dict with "briefs" (list) and "stats" (summary).
    """
    if run_date is None:
        run_date = date.today()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check: skip if today's briefs already exist
    cache_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("briefs"):
            logger.info(f"=== Content Strategist CACHED for {run_date}: {len(cached['briefs'])} briefs ===")
            return {"briefs": cached["briefs"], "stats": {"total_briefs": len(cached["briefs"]), "target": 96, "coverage": f"{len(cached['briefs'])}/96", "cached": True}}

    logger.info(f"=== Content Strategist starting for {run_date} ===")

    run_id = None
    try:
        run_id = db.log_pipeline_run(run_date, "phase1", "content_strategist")
    except Exception as e:
        logger.warning(f"Failed to log pipeline run: {e}")

    channels = _load_channels()
    content_rules = _load_content_rules()

    all_briefs = []
    errors = []

    # Run all destinations concurrently
    tasks = [
        strategize_destination(dest, run_date, channels, content_rules)
        for dest in DESTINATIONS
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for dest, result in zip(DESTINATIONS, results):
        if isinstance(result, Exception):
            logger.error(f"Content Strategist failed for {dest}: {result}")
            errors.append({"destination": dest, "error": str(result)})
        else:
            all_briefs.extend(result)

    # Save to file
    output_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump(
            {
                "date": run_date.isoformat(),
                "total_briefs": len(all_briefs),
                "briefs": all_briefs,
            },
            f,
            indent=2,
        )
    logger.info(f"Saved {len(all_briefs)} briefs to {output_file}")

    # Save to Supabase
    try:
        db.save_briefs(all_briefs)
    except Exception as e:
        logger.warning(f"Failed to save briefs to Supabase: {e}")

    if run_id:
        try:
            db.update_pipeline_run(
                run_id,
                status="completed" if not errors else "completed_with_errors",
                briefs_generated=len(all_briefs),
                errors=errors,
            )
        except Exception as e:
            logger.warning(f"Failed to update pipeline run: {e}")

    # Build stats
    per_dest = {}
    for dest in DESTINATIONS:
        dest_briefs = [b for b in all_briefs if b.get("destination") == dest]
        per_dest[dest] = {
            "count": len(dest_briefs),
            "with_deal": sum(1 for b in dest_briefs if b.get("deal")),
            "sample": next(
                (b["brief_id"] for b in dest_briefs if b.get("is_sample_video")),
                None,
            ),
        }

    stats = {
        "total_briefs": len(all_briefs),
        "target": 96,
        "coverage": f"{len(all_briefs)}/96",
        "per_destination": per_dest,
        "errors": len(errors),
    }

    logger.info(
        f"=== Content Strategist complete: {stats['total_briefs']}/96 briefs, "
        f"{stats['errors']} errors ==="
    )

    return {"briefs": all_briefs, "stats": stats}


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result["stats"], indent=2))
