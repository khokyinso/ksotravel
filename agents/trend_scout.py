"""Agent 1: Trend Scout

Identifies 12+ trending travel topics per destination (144+ signals daily).
Detects trending video FORMATS in addition to topics.

Source priority:
  P1: TikTok Creative Center — trending hashtags, sounds, formats
  P2: TikTok search autocomplete — what users are actively searching
  P3: Competitor TikTok/IG accounts — outsized engagement detection
  P4: Instagram Reels hashtags — confirmation signal
  P5: Reddit — discussion-based trends
  P6: Google Trends — search validation (secondary)
  P7: Seasonal calendar — always-on baseline

Model: Claude Haiku 4.5
Schedule: 5:00 AM EST daily
Output: data/trends_{date}.json
"""

import asyncio
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import anthropic
import httpx
import praw
from dotenv import load_dotenv
from loguru import logger

from utils import supabase_client as db

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

from config.constants import DESTINATIONS, VIDEO_FORMATS as SHARED_VIDEO_FORMATS, HOOK_ANGLES as SHARED_HOOK_ANGLES

# TikTok search queries per destination
TIKTOK_SEARCH_QUERIES = {
    "japan": ["japan travel", "japan tips", "tokyo travel", "japan 2026"],
    "greece": ["greece travel", "santorini tips", "greek islands", "athens travel"],
    "italy": ["italy travel", "rome tips", "amalfi coast", "italy 2026"],
    "korea": ["korea travel", "seoul tips", "korea food", "kpop travel"],
    "thailand": ["thailand travel", "bangkok tips", "thai islands", "thailand 2026"],
    "mexico": ["mexico travel", "tulum tips", "mexico city", "cenote mexico"],
    "portugal": ["portugal travel", "lisbon tips", "algarve", "porto travel"],
    "spain": ["spain travel", "barcelona tips", "madrid travel", "spain 2026"],
    "france": ["france travel", "paris tips", "french riviera", "france 2026"],
    "turkey": ["turkey travel", "istanbul tips", "cappadocia", "turkey 2026"],
    "poland": ["poland travel", "krakow tips", "warsaw travel", "poland budget"],
    "china": ["china travel", "beijing tips", "china visa", "shanghai travel"],
}

# Competitor accounts to monitor per destination
COMPETITOR_ACCOUNTS_TIKTOK = {
    "japan": ["@japanguide", "@tokyocheapo", "@aikidonwanderlust"],
    "greece": ["@greecetravelgr", "@visitgreece"],
    "italy": ["@waltersitaly", "@visititaly"],
    "korea": ["@koreatravel", "@seoulguide"],
    "thailand": ["@thailandtravel", "@bangkokguide"],
    "mexico": ["@mexicotravelguide", "@cdmxguide"],
    "portugal": ["@visitportugal", "@lisbonguide"],
    "spain": ["@spaintravel", "@barcelonaguide"],
    "france": ["@parisjetaime", "@francetourisme"],
    "turkey": ["@goturkey", "@istanbulguide"],
    "poland": ["@visitpoland", "@krakowguide"],
    "china": ["@visitchina", "@chinatravelguide"],
}

# Reddit subreddits per destination
REDDIT_SUBS = {
    "japan": ["JapanTravel", "JapanTips"],
    "greece": ["greece", "travel"],
    "italy": ["ItalyTravel", "travel"],
    "korea": ["korea", "travel"],
    "thailand": ["ThailandTourism", "travel"],
    "mexico": ["mexicotravel", "travel"],
    "portugal": ["PortugalExpats", "travel"],
    "spain": ["spain", "travel"],
    "france": ["france", "travel"],
    "turkey": ["turkey", "travel"],
    "poland": ["poland", "travel"],
    "china": ["Chinavisa", "china", "travel"],
}

# Use shared constants (imported at top)
VIDEO_FORMATS = SHARED_VIDEO_FORMATS
HOOK_ANGLES = SHARED_HOOK_ANGLES

TREND_SCOUT_SYSTEM_PROMPT = """You are the Trend Scout for @insearchofkso travel channels.
Analyze raw signals and produce exactly 12 structured trend objects per destination.
Each must be a unique, specific, actionable travel topic for short-form video.
Signals are prioritized: TikTok signals > competitor content > Instagram > Reddit > Google Trends > seasonal.

RULES:
- Each topic must be specific (real prices, real place names, real dates)
- Suggested hooks must be ≤8 words
- Prioritize "warning" and "hack" angles — they outperform
- Include at least 2 "warning" or "hack" topics
- Mix categories — no more than 3 of the same category
- Assign a video_format to each trend based on what's trending AND what fits the topic
- If a format is trending (from detected signals), prefer it
- Suggested lengths: 15s (single tip), 30s (tip + context), 45-60s (listicle/comparison)

Return ONLY a JSON array of 12 objects with these fields:
- topic (string): specific topic title
- hook_angle (string): one of ["warning", "hack", "secret", "timing", "comparison", "listicle", "story", "reaction"]
- urgency (string): "high", "medium", or "low"
- search_volume_trend (string): "rising", "stable", or "seasonal"
- content_category (string): one of ["transport", "attraction", "food_tour", "accommodation", "experience", "day_trip", "guided_tour"]
- suggested_hook (string): ≤8 words, compelling hook line
- suggested_length_seconds (integer): 15, 30, 45, or 60
- video_format (string): one of ["green_screen_text", "pov_walking", "split_screen", "photo_slideshow", "series_part", "stitch_reaction", "map_zoom", "before_after", "countdown_list", "storytime"]
- source_signal (string): which source inspired this trend

Return ONLY the JSON array, no other text."""


def _load_seasonal_calendar() -> dict:
    with open(CONFIG_DIR / "seasonal_calendar.json") as f:
        return json.load(f)


def _load_content_rules() -> dict:
    with open(CONFIG_DIR / "content_rules.json") as f:
        return json.load(f)


# ── P1: TikTok Creative Center ───────────────────────────────────────────


async def _scrape_tiktok_creative_center(destination: str) -> list[dict]:
    """Scrape trending hashtags and sounds from TikTok Creative Center.

    Uses Playwright to scrape the public TikTok Creative Center page
    which shows trending hashtags, sounds, and creator content.
    """
    signals = []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — skipping TikTok Creative Center")
        return []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )

            # Scrape trending hashtags
            url = f"https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en?period=7&region=US"
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Extract hashtag elements
            hashtag_elements = await page.query_selector_all('[class*="hashtag"], [class*="CardPc_title"], [class*="title"]')
            for el in hashtag_elements[:20]:
                text = await el.inner_text()
                text = text.strip().lstrip("#")
                if not text or len(text) < 3:
                    continue
                # Filter for travel-related hashtags for this destination
                dest_terms = [destination, destination.title()]
                travel_terms = ["travel", "trip", "tour", "visit", "food", "hotel", "flight", "beach", "temple", "city"]
                if any(term.lower() in text.lower() for term in dest_terms + travel_terms):
                    signals.append({
                        "topic": f"#{text}",
                        "source": "tiktok_creative_center",
                        "type": "trending_hashtag",
                        "platform": "tiktok",
                    })

            # Scrape trending sounds/music
            sound_url = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en?period=7&region=US"
            await page.goto(sound_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            sound_elements = await page.query_selector_all('[class*="music"], [class*="CardPc_title"], [class*="title"]')
            for el in sound_elements[:10]:
                text = await el.inner_text()
                text = text.strip()
                if text and len(text) > 2:
                    signals.append({
                        "topic": f"Trending sound: {text}",
                        "source": "tiktok_creative_center",
                        "type": "trending_sound",
                        "platform": "tiktok",
                    })

            await browser.close()

    except Exception as e:
        logger.warning(f"TikTok Creative Center scrape failed for {destination}: {e}")

    logger.info(f"TikTok Creative Center: {len(signals)} signals for {destination}")
    return signals


# ── P2: TikTok Search Autocomplete ───────────────────────────────────────


async def _scrape_tiktok_search(destination: str) -> list[dict]:
    """Scrape TikTok search suggestions to see what users are searching."""
    signals = []
    queries = TIKTOK_SEARCH_QUERIES.get(destination, [f"{destination} travel"])

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — skipping TikTok search")
        return []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )

            for query in queries:
                try:
                    # TikTok search page
                    search_url = f"https://www.tiktok.com/search?q={query.replace(' ', '%20')}"
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(2)

                    # Extract video descriptions from search results
                    desc_elements = await page.query_selector_all('[class*="desc"], [class*="caption"], [data-e2e="search-card-desc"]')
                    for el in desc_elements[:5]:
                        text = await el.inner_text()
                        text = text.strip()
                        if text and len(text) > 10:
                            signals.append({
                                "topic": text[:120],
                                "source": "tiktok_search",
                                "type": "search_result",
                                "query": query,
                                "platform": "tiktok",
                            })

                    # Extract related search suggestions
                    suggestion_elements = await page.query_selector_all('[class*="suggest"], [class*="related"], [data-e2e*="search"]')
                    for el in suggestion_elements[:5]:
                        text = await el.inner_text()
                        text = text.strip()
                        if text and len(text) > 3:
                            signals.append({
                                "topic": text[:80],
                                "source": "tiktok_search_suggest",
                                "type": "search_suggestion",
                                "query": query,
                                "platform": "tiktok",
                            })

                except Exception as e:
                    logger.debug(f"TikTok search failed for '{query}': {e}")
                    continue

            await browser.close()

    except Exception as e:
        logger.warning(f"TikTok search scrape failed for {destination}: {e}")

    logger.info(f"TikTok search: {len(signals)} signals for {destination}")
    return signals


# ── P3: Competitor Monitoring ─────────────────────────────────────────────


async def _scrape_competitor_accounts(destination: str) -> list[dict]:
    """Monitor competitor TikTok accounts for outsized engagement."""
    signals = []
    accounts = COMPETITOR_ACCOUNTS_TIKTOK.get(destination, [])

    if not accounts:
        return []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — skipping competitor monitoring")
        return []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )

            for account in accounts:
                try:
                    handle = account.lstrip("@")
                    profile_url = f"https://www.tiktok.com/@{handle}"
                    await page.goto(profile_url, wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(2)

                    # Extract recent video descriptions and engagement
                    video_elements = await page.query_selector_all('[class*="video-feed"] [class*="desc"], [data-e2e="user-post-item-desc"]')
                    for el in video_elements[:3]:
                        text = await el.inner_text()
                        text = text.strip()
                        if text and len(text) > 10:
                            signals.append({
                                "topic": text[:120],
                                "source": f"competitor/{handle}",
                                "type": "competitor_content",
                                "platform": "tiktok",
                                "account": account,
                            })

                except Exception as e:
                    logger.debug(f"Failed to scrape competitor {account}: {e}")
                    continue

            await browser.close()

    except Exception as e:
        logger.warning(f"Competitor scrape failed for {destination}: {e}")

    logger.info(f"Competitor monitoring: {len(signals)} signals for {destination}")
    return signals


# ── P4: Instagram Reels Hashtags ──────────────────────────────────────────


async def _scrape_instagram_hashtags(destination: str) -> list[dict]:
    """Check Instagram hashtag top posts for travel trends (confirmation signal).

    Uses Meta Graph API if META_ACCESS_TOKEN is available,
    otherwise falls back to Playwright scrape (less reliable due to Meta blocking).
    """
    signals = []
    access_token = os.getenv("META_ACCESS_TOKEN")

    hashtags = [
        f"{destination}travel",
        f"{destination}tips",
        f"visit{destination}",
        f"{destination}2026",
    ]

    if access_token:
        # Use Meta Graph API for hashtag search
        async with httpx.AsyncClient(timeout=20) as client:
            for tag in hashtags:
                try:
                    # Search for hashtag ID
                    resp = await client.get(
                        "https://graph.facebook.com/v19.0/ig_hashtag_search",
                        params={"q": tag, "user_id": os.getenv("INSTAGRAM_ACCOUNT_ID", ""), "access_token": access_token},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        hashtag_ids = data.get("data", [])
                        if hashtag_ids:
                            # Get top media for this hashtag
                            hid = hashtag_ids[0]["id"]
                            media_resp = await client.get(
                                f"https://graph.facebook.com/v19.0/{hid}/top_media",
                                params={
                                    "user_id": os.getenv("INSTAGRAM_ACCOUNT_ID", ""),
                                    "fields": "caption,like_count,comments_count,media_type",
                                    "access_token": access_token,
                                },
                            )
                            if media_resp.status_code == 200:
                                media_data = media_resp.json().get("data", [])
                                for post in media_data[:3]:
                                    caption = post.get("caption", "")
                                    if caption:
                                        signals.append({
                                            "topic": caption[:120],
                                            "source": f"instagram/#{tag}",
                                            "type": "instagram_top_post",
                                            "platform": "instagram",
                                            "likes": post.get("like_count", 0),
                                            "comments": post.get("comments_count", 0),
                                        })
                except Exception as e:
                    logger.debug(f"Instagram API error for #{tag}: {e}")
    else:
        logger.info("META_ACCESS_TOKEN not set — skipping Instagram hashtag scrape")

    logger.info(f"Instagram: {len(signals)} signals for {destination}")
    return signals


# ── P5: Reddit ────────────────────────────────────────────────────────────


def _get_reddit_signals(destination: str) -> list[dict]:
    """Scrape trending topics from relevant subreddits."""
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.warning("Reddit credentials not set — skipping Reddit signals")
        return []

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent="kso-travel-automation/1.0",
        )
    except Exception as e:
        logger.error(f"Reddit connection failed: {e}")
        return []

    subs = REDDIT_SUBS.get(destination, ["travel"])
    signals = []

    for sub_name in subs:
        try:
            subreddit = reddit.subreddit(sub_name)
            for post in subreddit.hot(limit=10):
                if post.score < 20:
                    continue
                signals.append({
                    "topic": post.title,
                    "source": f"reddit/r/{sub_name}",
                    "type": "reddit_hot",
                    "platform": "reddit",
                    "score": post.score,
                    "url": f"https://reddit.com{post.permalink}",
                })
        except Exception as e:
            logger.warning(f"Failed to scrape r/{sub_name}: {e}")
            continue

    logger.info(f"Reddit: {len(signals)} signals for {destination}")
    return signals


# ── P6: Google Trends (demoted to validation) ────────────────────────────


async def _get_google_trends_signals(destination: str) -> list[dict]:
    """Fetch rising travel queries from Google Trends — secondary validation."""
    api_key = os.getenv("GOOGLE_TRENDS_API_KEY")
    if not api_key:
        logger.info("Google Trends API key not set — skipping (secondary source)")
        return []

    search_terms = [
        f"{destination} travel",
        f"{destination} tips 2026",
        f"visit {destination}",
    ]

    signals = []
    async with httpx.AsyncClient(timeout=20) as client:
        for term in search_terms:
            try:
                resp = await client.get(
                    "https://trends.googleapis.com/trends/api/dailytrends",
                    params={"hl": "en-US", "geo": "US", "ns": 15},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 200:
                    signals.append({
                        "topic": term,
                        "source": "google_trends",
                        "type": "search_trend",
                        "platform": "google",
                        "search_volume_trend": "rising",
                    })
            except Exception as e:
                logger.debug(f"Google Trends error for '{term}': {e}")

    logger.info(f"Google Trends: {len(signals)} signals for {destination}")
    return signals


# ── P7: Seasonal Calendar ────────────────────────────────────────────────


def _get_seasonal_signals(destination: str, run_date: date) -> list[dict]:
    """Check if any seasonal events are approaching for this destination."""
    calendar = _load_seasonal_calendar()
    events = calendar.get(destination, [])
    signals = []

    for event in events:
        start_str = f"{run_date.year}-{event['start']}"
        end_str = f"{run_date.year}-{event['end']}"
        try:
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        if end < start:
            end = end.replace(year=end.year + 1)

        days_until = (start - run_date).days
        days_since_end = (run_date - end).days

        if -7 <= days_until <= 30 or (days_until < 0 and days_since_end < 0):
            urgency = "high" if days_until <= 7 else event.get("urgency", "medium")
            signals.append({
                "topic": event["event"],
                "source": "seasonal_calendar",
                "type": "seasonal",
                "platform": "internal",
                "hook_angle": event.get("content_angle", "timing"),
                "urgency": urgency,
            })

    logger.info(f"Seasonal: {len(signals)} signals for {destination}")
    return signals


# ── Trending Format Detection ─────────────────────────────────────────────

VISUAL_FORMAT_PROMPT = """You are analyzing TikTok cover thumbnails from top-performing travel content.
Classify each thumbnail's visual format and identify patterns.

For each thumbnail, identify:
- video_format: one of ["green_screen_text", "pov_walking", "split_screen", "photo_slideshow", "series_part", "stitch_reaction", "map_zoom", "before_after", "countdown_list", "storytime", "talking_head", "b_roll_montage"]
- text_overlay_style: "bold_centered", "subtitle_bottom", "multi_line_list", "minimal", "none"
- color_scheme: dominant colors (e.g., "warm_orange", "cool_blue", "high_contrast", "muted")
- hook_technique: what visual element grabs attention first

Return ONLY a JSON object:
{
  "thumbnails": [
    {"index": 1, "video_format": "...", "text_overlay_style": "...", "color_scheme": "...", "hook_technique": "..."},
    ...
  ],
  "trending_formats": [{"format": "...", "frequency": N, "text_style": "...", "color_trend": "..."}],
  "recommendation": "Brief summary of what visual styles are working for this destination"
}"""


async def _detect_trending_formats(destination: str) -> list[dict]:
    """Detect which video formats are currently trending on TikTok.

    Two-tier approach:
    1. Text-based detection from captions/descriptions (fast, free)
    2. Visual analysis of cover thumbnails with Sonnet vision (accurate, costs tokens)

    Visual analysis is controlled by VISUAL_FORMAT_ANALYSIS env var (default: true).
    """
    signals = []
    use_vision = os.getenv("VISUAL_FORMAT_ANALYSIS", "true").lower() == "true"

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — skipping format detection")
        return []

    cover_images: list[str] = []  # base64 encoded thumbnails
    descriptions: list[str] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            )

            # Search for trending travel content in this destination
            search_url = f"https://www.tiktok.com/search/video?q={destination}%20travel%20tips"
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)

            # Extract video descriptions for text-based analysis
            desc_elements = await page.query_selector_all(
                '[class*="desc"], [class*="caption"], [data-e2e="search-card-desc"]'
            )
            for el in desc_elements[:15]:
                text = await el.inner_text()
                if text.strip():
                    descriptions.append(text.strip()[:200])

            # Extract cover image thumbnails for vision analysis
            if use_vision:
                import base64
                import httpx

                # TikTok search results show video thumbnails as img or poster
                img_elements = await page.query_selector_all(
                    '[class*="poster"] img, [class*="thumb"] img, '
                    '[data-e2e="search-card-image"] img, video[poster]'
                )

                async with httpx.AsyncClient(timeout=15) as http_client:
                    for el in img_elements[:10]:
                        try:
                            # Try img src first, then video poster
                            src = await el.get_attribute("src")
                            if not src:
                                src = await el.get_attribute("poster")
                            if not src or not src.startswith("http"):
                                continue

                            resp = await http_client.get(src)
                            if resp.status_code == 200 and len(resp.content) > 1000:
                                b64 = base64.standard_b64encode(resp.content).decode("utf-8")
                                cover_images.append(b64)
                        except Exception as e:
                            logger.debug(f"Failed to download thumbnail: {e}")
                            continue

                logger.info(f"Downloaded {len(cover_images)} cover thumbnails for {destination}")

            await browser.close()

    except Exception as e:
        logger.warning(f"Format detection scrape failed for {destination}: {e}")

    # ── Tier 1: Text-based format detection (always runs) ──
    format_indicators = {
        "series_part": [r"part\s*\d", r"ep\s*\d", r"\d+/\d+"],
        "countdown_list": [r"top\s*\d", r"\d+\s*things", r"\d+\s*places", r"\d+\s*tips"],
        "before_after": [r"expectation.*reality", r"what i expected", r"vs\.?\s"],
        "pov_walking": [r"pov[\s:]", r"walking tour", r"come with me"],
        "storytime": [r"storytime", r"story time", r"what happened"],
        "split_screen": [r"\bvs\b", r"compared", r"which is better"],
    }

    format_counts: dict[str, int] = {}
    for desc in descriptions:
        desc_lower = desc.lower()
        for fmt, patterns in format_indicators.items():
            for pat in patterns:
                if re.search(pat, desc_lower):
                    format_counts[fmt] = format_counts.get(fmt, 0) + 1
                    break

    for fmt, count in sorted(format_counts.items(), key=lambda x: x[1], reverse=True):
        if count >= 2:
            signals.append({
                "topic": f"Trending format: {fmt}",
                "source": "tiktok_format_analysis",
                "type": "trending_format",
                "platform": "tiktok",
                "format": fmt,
                "frequency": count,
                "detection": "text",
            })

    # ── Tier 2: Vision-based format detection (if enabled + thumbnails available) ──
    if use_vision and cover_images:
        try:
            from utils.token_tracker import tracked_create

            # Build vision content with thumbnails
            content: list[dict] = [
                {
                    "type": "text",
                    "text": (
                        f"Analyze these {len(cover_images)} cover thumbnails from "
                        f"top-performing TikTok travel videos about {destination.title()}. "
                        f"Identify the visual format, text overlay style, color scheme, "
                        f"and hook technique for each."
                    ),
                }
            ]

            for i, b64_img in enumerate(cover_images):
                # Detect media type (most TikTok thumbnails are JPEG)
                media_type = "image/jpeg"
                if b64_img[:4] == "iVBO":
                    media_type = "image/png"

                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64_img,
                    },
                })
                content.append({
                    "type": "text",
                    "text": f"Thumbnail {i + 1}/{len(cover_images)}",
                })

            text, _usage = tracked_create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": VISUAL_FORMAT_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": content}],
                agent_name="trend_scout_vision",
                context={"destination": destination, "thumbnails": len(cover_images)},
            )

            # Parse response
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            vision_result = json.loads(text)

            # Add vision-detected formats to signals
            for fmt_data in vision_result.get("trending_formats", []):
                fmt = fmt_data.get("format", "")
                if fmt in VIDEO_FORMATS or fmt in ["talking_head", "b_roll_montage"]:
                    signals.append({
                        "topic": f"Visual trend: {fmt} ({fmt_data.get('text_style', '')})",
                        "source": "tiktok_vision_analysis",
                        "type": "trending_format",
                        "platform": "tiktok",
                        "format": fmt,
                        "frequency": fmt_data.get("frequency", 1),
                        "text_style": fmt_data.get("text_style", ""),
                        "color_trend": fmt_data.get("color_trend", ""),
                        "detection": "vision",
                    })

            # Store the recommendation for Agent 3
            recommendation = vision_result.get("recommendation", "")
            if recommendation:
                signals.append({
                    "topic": f"Visual style insight: {recommendation[:120]}",
                    "source": "tiktok_vision_analysis",
                    "type": "visual_style_recommendation",
                    "platform": "tiktok",
                    "detection": "vision",
                })

            logger.info(
                f"Vision format analysis: {len(vision_result.get('trending_formats', []))} "
                f"formats detected for {destination}"
            )

        except Exception as e:
            logger.warning(f"Vision format analysis failed for {destination}: {e}")

    logger.info(f"Format detection: {len(signals)} signals for {destination}")
    return signals


# ── AI Classification ─────────────────────────────────────────────────────


def _classify_trends_with_ai(
    destination: str,
    raw_signals: list[dict],
    run_date: date,
) -> list[dict]:
    """Use Claude Haiku to classify raw signals into structured trend objects.

    Now includes video_format assignment based on detected trending formats.
    """
    from utils.token_tracker import tracked_create

    rules = _load_content_rules()
    hook_angles = rules["hook_angles_ranked"]
    categories = rules["deal_categories"]

    # Separate format signals from topic signals
    format_signals = [s for s in raw_signals if s.get("type") == "trending_format"]
    topic_signals = [s for s in raw_signals if s.get("type") != "trending_format"]

    # Prioritize signals: TikTok > Competitor > Instagram > Reddit > Google > Seasonal
    priority_order = {
        "tiktok_creative_center": 1, "tiktok_search": 2, "tiktok_search_suggest": 2,
        "competitor_content": 3, "instagram_top_post": 4,
        "reddit_hot": 5, "search_trend": 6, "seasonal": 7, "fallback": 8,
    }
    topic_signals.sort(key=lambda s: priority_order.get(s.get("type", ""), 99))

    signals_text = json.dumps(topic_signals[:40], indent=2, default=str)
    formats_text = json.dumps(format_signals, indent=2, default=str) if format_signals else "No format data available — use your best judgment."

    dest_specific = ""
    if destination == "china":
        dest_specific = "CHINA SPECIFIC: Include at least 1 visa/entry tip."
    elif destination == "turkey":
        dest_specific = "TURKEY SPECIFIC: All prices must be in USD, never Turkish Lira."
    elif destination == "france":
        dest_specific = "FRANCE SPECIFIC: Include at least 1 underrated-vs-overtouristed angle."
    elif destination == "poland":
        dest_specific = "POLAND SPECIFIC: Include at least 1 underrated-vs-overtouristed or budget angle."

    prompt = f"""Destination: {destination.title()}
Today's date: {run_date.isoformat()}

RAW TOPIC SIGNALS (prioritized):
{signals_text}

TRENDING VIDEO FORMATS DETECTED:
{formats_text}

Hook angles (ranked by performance): {json.dumps(hook_angles)}
Content categories: {json.dumps(categories)}
{f"{dest_specific}" if dest_specific else ""}"""

    text, _usage = tracked_create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        system=[{
            "type": "text",
            "text": TREND_SCOUT_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
        agent_name="trend_scout",
        context={"destination": destination},
    )
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        trends = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response for {destination}: {e}")
        logger.debug(f"Raw response: {text[:500]}")
        return []

    validated = []
    for t in trends:
        if not isinstance(t, dict):
            continue
        t["destination"] = destination
        if t.get("hook_angle") not in hook_angles:
            t["hook_angle"] = "hack"
        if t.get("suggested_length_seconds") not in (15, 30, 45, 60):
            t["suggested_length_seconds"] = 30
        if t.get("video_format") not in VIDEO_FORMATS:
            t["video_format"] = "green_screen_text"
        validated.append(t)

    return validated


# ── Main Orchestration ────────────────────────────────────────────────────


async def scout_destination(destination: str, run_date: date) -> list[dict]:
    """Run full trend scouting for one destination across all sources."""
    logger.info(f"Scouting trends for {destination}...")

    # Gather signals from all sources concurrently
    # P1-P4 are async (Playwright/HTTP), P5 is sync (PRAW), P7 is sync (local)
    tiktok_cc_task = _scrape_tiktok_creative_center(destination)
    tiktok_search_task = _scrape_tiktok_search(destination)
    competitor_task = _scrape_competitor_accounts(destination)
    instagram_task = _scrape_instagram_hashtags(destination)
    google_task = _get_google_trends_signals(destination)
    format_task = _detect_trending_formats(destination)

    # Run async sources concurrently
    async_results = await asyncio.gather(
        tiktok_cc_task, tiktok_search_task, competitor_task,
        instagram_task, google_task, format_task,
        return_exceptions=True,
    )

    # Run sync sources
    reddit_signals = _get_reddit_signals(destination)
    seasonal_signals = _get_seasonal_signals(destination, run_date)

    # Combine all raw signals
    raw_signals = []

    source_names = [
        "tiktok_creative_center", "tiktok_search", "competitors",
        "instagram", "google_trends", "format_detection",
    ]
    for name, result in zip(source_names, async_results):
        if isinstance(result, Exception):
            logger.warning(f"{name} failed for {destination}: {result}")
        elif result:
            raw_signals.extend(result)

    raw_signals.extend(reddit_signals)
    raw_signals.extend(seasonal_signals)

    if not raw_signals:
        raw_signals = [{"topic": f"{destination} travel tips 2026", "source": "fallback", "type": "fallback"}]

    logger.info(f"Collected {len(raw_signals)} raw signals for {destination}")

    # Classify with AI
    trends = _classify_trends_with_ai(destination, raw_signals, run_date)
    logger.info(f"Generated {len(trends)} trends for {destination}")
    return trends


async def run(run_date: date | None = None) -> dict:
    """Run Trend Scout for all 12 destinations.

    Returns:
        dict with "trends" (list) and "stats" (summary).
    """
    if run_date is None:
        run_date = date.today()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Cache check: skip if today's trends already exist
    cache_file = DATA_DIR / f"trends_{run_date.isoformat()}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            cached = json.load(f)
        if cached.get("trends"):
            logger.info(f"=== Trend Scout CACHED for {run_date}: {len(cached['trends'])} trends ===")
            return {"trends": cached["trends"], "stats": {"total_trends": len(cached["trends"]), "cached": True}}

    logger.info(f"=== Trend Scout starting for {run_date} ===")

    run_id = None
    try:
        run_id = db.log_pipeline_run(run_date, "phase1", "trend_scout")
    except Exception as e:
        logger.warning(f"Failed to log pipeline run: {e}")

    all_trends = []
    errors = []

    # Run destinations concurrently (but limit concurrency to avoid rate limits)
    semaphore = asyncio.Semaphore(4)  # Max 4 destinations at once

    async def scout_with_limit(dest: str) -> list[dict]:
        async with semaphore:
            return await scout_destination(dest, run_date)

    tasks = [scout_with_limit(dest) for dest in DESTINATIONS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for dest, result in zip(DESTINATIONS, results):
        if isinstance(result, Exception):
            logger.error(f"Trend Scout failed for {dest}: {result}")
            errors.append({"destination": dest, "error": str(result)})
        else:
            all_trends.extend(result)

    # Save to file
    output_file = DATA_DIR / f"trends_{run_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump({"date": run_date.isoformat(), "trends": all_trends}, f, indent=2)
    logger.info(f"Saved {len(all_trends)} trends to {output_file}")

    # Save to Supabase
    try:
        db.save_trends(all_trends, run_date)
    except Exception as e:
        logger.warning(f"Failed to save trends to Supabase: {e}")

    if run_id:
        try:
            db.update_pipeline_run(
                run_id,
                status="completed" if not errors else "completed_with_errors",
                briefs_generated=len(all_trends),
                errors=errors,
            )
        except Exception as e:
            logger.warning(f"Failed to update pipeline run: {e}")

    # Build source breakdown
    source_counts: dict[str, int] = {}
    format_counts: dict[str, int] = {}
    for t in all_trends:
        src = t.get("source_signal", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
        fmt = t.get("video_format", "unknown")
        format_counts[fmt] = format_counts.get(fmt, 0) + 1

    stats = {
        "total_trends": len(all_trends),
        "per_destination": {
            dest: len([t for t in all_trends if t.get("destination") == dest])
            for dest in DESTINATIONS
        },
        "by_source": source_counts,
        "by_format": format_counts,
        "errors": len(errors),
    }
    logger.info(f"=== Trend Scout complete: {stats['total_trends']} trends, {stats['errors']} errors ===")
    logger.info(f"Source breakdown: {json.dumps(source_counts)}")
    logger.info(f"Format breakdown: {json.dumps(format_counts)}")

    return {"trends": all_trends, "stats": stats}


if __name__ == "__main__":
    result = asyncio.run(run())
    print(json.dumps(result["stats"], indent=2))
