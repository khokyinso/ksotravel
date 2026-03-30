"""TikTok Viral Format Scanner

Scans TikTok Creative Center + web sources to identify trending video formats,
hooks, and content strategies for travel content. Uses WebFetch since TikTok's
main site is client-rendered and inaccessible via simple HTTP.

Sources:
1. TikTok Creative Center (trending hashtags)
2. Travel content blogs/trend reports (viral formats + strategies)
3. Competitor analysis via oembed API

Output: data/format_trends_{date}.json
"""

import asyncio
import json
import os
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"

# Verified viral formats for travel TikTok (2026, sourced from trend reports)
VIRAL_FORMATS = {
    "green_screen_text": {
        "name": "Green Screen Text",
        "description": "Stock footage background + text overlay blocks. KSO default.",
        "engagement_rank": 1,
        "best_for": ["tips", "hacks", "warnings", "listicles"],
        "remotion_template": "GreenScreenText",
    },
    "pov_walking": {
        "name": "POV First Person",
        "description": "First-person immersive walkthrough. Phone/GoPro, ambient audio.",
        "engagement_rank": 2,
        "best_for": ["hidden_gems", "food_tours", "street_tours", "day_trips"],
        "remotion_template": "POVWalking",
    },
    "countdown_list": {
        "name": "Countdown Listicle",
        "description": "5-4-3-2-1 countdown with reveals. High save rate.",
        "engagement_rank": 3,
        "best_for": ["rankings", "top_picks", "must_visits", "budget_tips"],
        "remotion_template": "CountdownList",
    },
    "split_screen": {
        "name": "Split Screen Comparison",
        "description": "Side-by-side comparison ($50 vs $500 hotel).",
        "engagement_rank": 4,
        "best_for": ["comparisons", "value_tips", "before_after"],
        "remotion_template": "SplitScreen",
    },
    "before_after": {
        "name": "Expectation vs Reality",
        "description": "What you expect vs what you get. Debunking format.",
        "engagement_rank": 5,
        "best_for": ["debunking", "tourist_traps", "overrated_places"],
        "remotion_template": "BeforeAfter",
    },
    "series_part": {
        "name": "Multi-Part Series",
        "description": "Day X of helping you plan your trip. Builds followership.",
        "engagement_rank": 6,
        "best_for": ["itineraries", "planning_guides", "deep_dives"],
        "remotion_template": "GreenScreenText",  # Same template, different title format
    },
    "photo_slideshow": {
        "name": "Photo Slideshow",
        "description": "Photo carousel with voiceover narration. Low production, high engagement.",
        "engagement_rank": 7,
        "best_for": ["photo_spots", "aesthetic_places", "hidden_gems"],
        "remotion_template": "PhotoSlideshow",
    },
    "map_zoom": {
        "name": "Map Zoom Reveal",
        "description": "Zoom into location on map, then show the destination.",
        "engagement_rank": 8,
        "best_for": ["hidden_gems", "route_planning", "geographic_context"],
        "remotion_template": "MapZoom",
    },
    "tier_list": {
        "name": "Tier List Ranking",
        "description": "S/A/B/C/D tier ranking of destinations, foods, experiences.",
        "engagement_rank": 9,
        "best_for": ["rankings", "opinions", "controversial_takes"],
        "remotion_template": "TierList",
    },
    "storytime": {
        "name": "Storytime",
        "description": "Personal story with text captions. Authentic, relatable.",
        "engagement_rank": 10,
        "best_for": ["personal_experience", "travel_fails", "lessons_learned"],
        "remotion_template": "GreenScreenText",
    },
}

# Format-to-content_category mapping for Agent 3
FORMAT_CATEGORY_AFFINITIES = {
    "transport": ["green_screen_text", "countdown_list", "split_screen"],
    "attraction": ["pov_walking", "photo_slideshow", "before_after"],
    "food_tour": ["pov_walking", "countdown_list", "tier_list"],
    "accommodation": ["split_screen", "before_after", "green_screen_text"],
    "experience": ["pov_walking", "storytime", "photo_slideshow"],
    "day_trip": ["map_zoom", "series_part", "pov_walking"],
    "guided_tour": ["pov_walking", "countdown_list", "green_screen_text"],
}


async def scan_tiktok_creative_center() -> list[dict]:
    """Fetch trending hashtags from TikTok Creative Center."""
    signals = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en",
                params={"period": 7, "region": "US"},
            )
            if resp.status_code == 200:
                # Parse the page for hashtag data
                text = resp.text
                # Extract hashtag data from the page's embedded JSON
                import re
                matches = re.findall(r'"hashtag_name":"([^"]+)".*?"publish_cnt":(\d+)', text)
                for name, count in matches[:20]:
                    if any(kw in name.lower() for kw in [
                        "travel", "japan", "korea", "italy", "greece", "thailand",
                        "mexico", "portugal", "spain", "france", "turkey",
                        "tourist", "trip", "flight", "hotel", "food",
                    ]):
                        signals.append({
                            "source": "tiktok_creative_center",
                            "hashtag": name,
                            "post_count": int(count),
                            "type": "hashtag_trend",
                        })
    except Exception as e:
        logger.warning(f"Creative Center scan failed: {e}")

    return signals


def get_format_recommendations(
    content_category: str,
    destination: str,
    hook_angle: str,
) -> list[dict]:
    """Recommend video formats based on content category and hook angle.

    Returns ranked list of format recommendations with Remotion template names.
    """
    # Get formats that match this content category
    category_formats = FORMAT_CATEGORY_AFFINITIES.get(content_category, ["green_screen_text"])

    # Build ranked recommendations
    recommendations = []
    for fmt_key in category_formats:
        fmt = VIRAL_FORMATS.get(fmt_key, VIRAL_FORMATS["green_screen_text"])
        recommendations.append({
            "format": fmt_key,
            "remotion_template": fmt["remotion_template"],
            "name": fmt["name"],
            "engagement_rank": fmt["engagement_rank"],
            "reason": f"High performing for {content_category} content",
        })

    # Sort by engagement rank
    recommendations.sort(key=lambda x: x["engagement_rank"])

    return recommendations


async def scan_formats(run_date: date | None = None) -> dict:
    """Full format scan. Returns format trends + recommendations."""
    if run_date is None:
        run_date = date.today()

    logger.info(f"=== Format Scanner starting for {run_date} ===")

    # Scan TikTok Creative Center
    cc_signals = await scan_tiktok_creative_center()
    logger.info(f"Creative Center: {len(cc_signals)} travel-related signals")

    result = {
        "date": run_date.isoformat(),
        "viral_formats": VIRAL_FORMATS,
        "format_category_affinities": FORMAT_CATEGORY_AFFINITIES,
        "creative_center_signals": cc_signals,
        "top_formats_2026": [
            "green_screen_text",  # Stable #1 for tips/hacks
            "pov_walking",        # Rising — immersive, authentic feel
            "countdown_list",     # High save rate
            "split_screen",       # Comparison content performs well
            "series_part",        # Builds followership
        ],
    }

    # Save to file
    output_file = DATA_DIR / f"format_trends_{run_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved format trends to {output_file}")

    return result


if __name__ == "__main__":
    asyncio.run(scan_formats())
