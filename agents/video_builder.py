"""Agent 7: Video Builder (Local Mac Renderer)

Renders TikTok/Reels videos locally on Mac using Apple Silicon.
Fetches background footage from Pexels, composites text overlays
using Pillow + moviepy, uploads MP4s to Supabase Storage.

Model: None (no AI calls)
Schedule: 7:00 AM EST
Output: Rendered MP4 URLs in Supabase rendered_videos table
"""

import asyncio
import json
import os
import random
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from dotenv import load_dotenv
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

# Fix for Pillow 10+ removing ANTIALIAS (moviepy 1.x uses it)
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from utils import supabase_client as db

load_dotenv(override=True)

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_DIR = Path(__file__).parent.parent / "config"

# Video specs
WIDTH = 1080
HEIGHT = 1920
FPS = 24
FONT_SIZE = 36  # Match KSO TikTok style — readable but not huge
TITLE_FONT_SIZE = 40  # Series title slightly larger
TEXT_MARGIN_X = 50  # Left margin
TEXT_MARGIN_RIGHT = 200  # Right margin (keep text in left ~80%)
TEXT_MAX_WIDTH = WIDTH - TEXT_MARGIN_X - TEXT_MARGIN_RIGHT
TEXT_Y_START = 700  # Start in middle-lower area
LINE_HEIGHT = 46  # Line height within a paragraph
BLOCK_SPACING = 24  # Space between paragraph blocks
OUTLINE_WIDTH = 3  # Text outline/stroke thickness for readability
FADE_STAGGER = 1.5  # Seconds between each paragraph block appearing

# macOS font paths (try in order)
FONT_PATHS = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
]

BRAND_COLORS = {
    "japan": "#E8272A", "greece": "#0D5EAF", "italy": "#009246",
    "korea": "#00A693", "thailand": "#FFB400", "mexico": "#006847",
    "portugal": "#006600", "spain": "#AA151B", "france": "#002395",
    "turkey": "#E30A17", "poland": "#DC143C", "china": "#DE2910",
}

FOOTAGE_TAGS = {
    "japan": "tokyo street, cherry blossom japan, japanese temple",
    "greece": "santorini, greek island, athens acropolis",
    "italy": "rome colosseum, venice canal, amalfi coast",
    "korea": "seoul neon, korean temple, jeju island",
    "thailand": "bangkok temple, thai beach, street food thailand",
    "mexico": "mexico city, tulum ruins, cenote",
    "portugal": "lisbon tram, porto bridge, algarve coast",
    "spain": "barcelona gaudi, madrid plaza, seville",
    "france": "paris eiffel, provence lavender, nice coast",
    "turkey": "istanbul mosque, cappadocia balloon, turkish bazaar",
    "poland": "krakow square, warsaw old town, gdansk",
    "china": "shanghai skyline, great wall, beijing temple",
}

_footage_cache: dict[str, str] = {}


def _get_font(size: int = FONT_SIZE) -> ImageFont.FreeTypeFont:
    """Load a font, trying multiple paths."""
    for path in FONT_PATHS:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


# ── Pexels Footage ──────────────────────────────────────────────────────


_VISUAL_QUERIES = {
    # content_category -> visual search terms by destination
    "transport": {
        "japan": "japan bullet train shinkansen",
        "greece": "greece ferry boat sea",
        "italy": "italy train countryside",
        "korea": "seoul subway metro",
        "thailand": "bangkok tuk tuk street",
        "mexico": "mexico city bus street",
        "portugal": "lisbon tram yellow",
        "spain": "spain train station",
        "france": "paris metro train",
        "turkey": "istanbul ferry bosphorus",
        "poland": "warsaw tram city",
        "china": "china high speed train",
    },
    "accommodation": {
        "japan": "japanese ryokan traditional room",
        "greece": "santorini white hotel pool",
        "italy": "tuscany villa countryside",
        "korea": "korean hanok traditional house",
        "thailand": "thailand beach resort bungalow",
        "mexico": "mexico hacienda hotel",
        "portugal": "lisbon apartment view",
        "spain": "spain courtyard hotel",
        "france": "paris boutique hotel",
        "turkey": "cappadocia cave hotel",
        "poland": "krakow old town hotel",
        "china": "chinese traditional courtyard hotel",
    },
    "food_tour": {
        "japan": "japanese street food market",
        "greece": "greek food taverna",
        "italy": "italian pasta restaurant",
        "korea": "korean street food market",
        "thailand": "thai street food night market",
        "mexico": "mexican street tacos food",
        "portugal": "portuguese pasteis food",
        "spain": "spanish tapas bar",
        "france": "french bakery pastry",
        "turkey": "turkish kebab bazaar food",
        "poland": "polish market food",
        "china": "chinese street food dumpling",
    },
    "attraction": {
        "japan": "tokyo temple shrine",
        "greece": "acropolis athens ruins",
        "italy": "rome colosseum ancient",
        "korea": "seoul palace traditional",
        "thailand": "bangkok temple golden",
        "mexico": "mexico pyramid ancient ruins",
        "portugal": "sintra palace castle",
        "spain": "barcelona sagrada familia",
        "france": "paris eiffel tower",
        "turkey": "istanbul hagia sophia mosque",
        "poland": "krakow wawel castle",
        "china": "great wall china",
    },
    "experience": {
        "japan": "japan cultural experience",
        "greece": "greece island sailing",
        "italy": "italy wine tasting vineyard",
        "korea": "korea hanbok cultural",
        "thailand": "thailand elephant sanctuary",
        "mexico": "mexico cenote swimming",
        "portugal": "portugal surfing beach",
        "spain": "spain flamenco dance",
        "france": "france lavender provence",
        "turkey": "cappadocia hot air balloon",
        "poland": "poland salt mine underground",
        "china": "china tea ceremony",
    },
    "day_trip": {
        "japan": "kyoto bamboo grove path",
        "greece": "greek island village",
        "italy": "amalfi coast village",
        "korea": "korean countryside village",
        "thailand": "thailand island beach boat",
        "mexico": "mexico village colorful street",
        "portugal": "portugal coastal cliff",
        "spain": "spain village white houses",
        "france": "french village countryside",
        "turkey": "turkey pamukkale terraces",
        "poland": "poland mountain lake",
        "china": "china river village landscape",
    },
    "guided_tour": {
        "japan": "tokyo city walking tour",
        "greece": "athens walking tour guide",
        "italy": "rome walking tour",
        "korea": "seoul city walking",
        "thailand": "bangkok river boat tour",
        "mexico": "mexico city walking tour",
        "portugal": "lisbon walking tour",
        "spain": "barcelona walking tour",
        "france": "paris walking tour",
        "turkey": "istanbul walking tour bazaar",
        "poland": "krakow walking tour",
        "china": "beijing walking tour",
    },
}

# Fallback: strip non-visual words from topic
_NOISE_WORDS = {
    "hack", "hacks", "booking", "guide", "tip", "tips", "trick", "tricks",
    "save", "saving", "savings", "budget", "cheap", "free", "price", "cost",
    "hike", "alert", "warning", "deadline", "update", "secret", "hidden",
    "must", "best", "worst", "top", "avoid", "never", "always", "how",
    "why", "what", "when", "number", "vs", "versus",
}


def _build_visual_query(topic: str, destination: str, content_category: str) -> str:
    """Build a Pexels search query that returns visually relevant footage."""
    # Try category-specific visual query first
    cat_queries = _VISUAL_QUERIES.get(content_category, {})
    if destination in cat_queries:
        return cat_queries[destination]

    # Fallback: extract visual nouns from topic, skip noise words
    if topic:
        words = topic.split(":")[0].strip().split()
        visual_words = [w for w in words if w.lower() not in _NOISE_WORDS and len(w) > 2]
        if visual_words:
            query = " ".join(visual_words[:3]) + f" {destination}"
            return query

    # Last resort: generic destination footage
    tags = FOOTAGE_TAGS.get(destination, f"{destination} travel")
    return tags.split(",")[0].strip()


async def fetch_pexels_footage(
    destination: str, duration_hint: int, tmp_dir: str,
    topic: str = "", brief_id: str = "", content_category: str = "",
) -> str | None:
    """Fetch portrait video from Pexels matching the brief topic. Returns local path."""
    # Cache by brief_id so each video gets unique footage
    cache_key = brief_id or destination
    if cache_key in _footage_cache and Path(_footage_cache[cache_key]).exists():
        logger.info(f"[{destination}] Using cached footage for {cache_key}")
        return _footage_cache[cache_key]

    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        logger.error(f"[{destination}] PEXELS_API_KEY not set")
        return None

    query = _build_visual_query(topic, destination, content_category)
    logger.info(f"[{destination}] Searching Pexels for: '{query}' (category={content_category})")

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                "https://api.pexels.com/videos/search",
                params={
                    "query": query,
                    "per_page": 5,
                    "orientation": "portrait",
                    "size": "medium",
                },
                headers={"Authorization": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"[{destination}] Pexels returned {len(data.get('videos', []))} videos")
        except Exception as e:
            logger.error(f"[{destination}] Pexels API failed: {e}")
            return None

    videos = data.get("videos", [])
    if not videos:
        logger.warning(f"[{destination}] No videos found")
        return None

    random.shuffle(videos)

    for i, video in enumerate(videos):
        files = video.get("video_files", [])
        # Prefer 720p portrait for fast encode
        sd_files = [
            f for f in files
            if 720 <= f.get("height", 0) <= 1080 and f.get("width", 0) <= f.get("height", 0)
        ]
        if not sd_files:
            sd_files = [f for f in files if f.get("height", 0) >= 480]
        if not sd_files:
            sd_files = files
        if not sd_files:
            continue

        download_url = sd_files[0].get("link")
        if not download_url:
            continue

        logger.info(f"[{destination}] Downloading {sd_files[0].get('width')}x{sd_files[0].get('height')} for {cache_key}...")
        footage_path = os.path.join(tmp_dir, f"{cache_key}_footage.mp4")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as dl_client:
                async with dl_client.stream("GET", download_url) as dl_resp:
                    dl_resp.raise_for_status()
                    total = 0
                    with open(footage_path, "wb") as f:
                        async for chunk in dl_resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            total += len(chunk)
            logger.info(f"[{destination}] Downloaded {total / (1024*1024):.1f} MB")
            _footage_cache[cache_key] = footage_path
            return footage_path
        except Exception as e:
            logger.error(f"[{destination}] Download failed: {e}")
            continue

    logger.warning(f"[{destination}] Pexels failed — trying Pixabay fallback...")

    # ── Pixabay fallback ──
    pixabay_result = await _fetch_pixabay_footage(
        query, destination, cache_key, tmp_dir
    )
    if pixabay_result:
        return pixabay_result

    logger.error(f"[{destination}] All download attempts failed (Pexels + Pixabay)")
    return None


async def _fetch_pixabay_footage(
    query: str, destination: str, cache_key: str, tmp_dir: str,
) -> str | None:
    """Fetch portrait video from Pixabay as fallback. Returns local path."""
    api_key = os.getenv("PIXABAY_API_KEY")
    if not api_key:
        logger.warning(f"[{destination}] PIXABAY_API_KEY not set — skipping Pixabay")
        return None

    # Pixabay uses slightly different query style
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(
                "https://pixabay.com/api/videos/",
                params={
                    "key": api_key,
                    "q": query,
                    "per_page": 5,
                    "video_type": "film",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"[{destination}] Pixabay returned {data.get('totalHits', 0)} videos")
        except Exception as e:
            logger.error(f"[{destination}] Pixabay API failed: {e}")
            return None

    hits = data.get("hits", [])
    if not hits:
        logger.warning(f"[{destination}] No Pixabay videos found for '{query}'")
        return None

    random.shuffle(hits)

    for video in hits:
        videos_data = video.get("videos", {})
        # Prefer medium quality (typically 1280x720 or 960x540)
        for quality in ("medium", "small", "large"):
            vfile = videos_data.get(quality, {})
            download_url = vfile.get("url")
            if download_url:
                break
        else:
            continue

        width = vfile.get("width", 0)
        height = vfile.get("height", 0)
        logger.info(f"[{destination}] Pixabay downloading {width}x{height} for {cache_key}...")

        footage_path = os.path.join(tmp_dir, f"{cache_key}_footage.mp4")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as dl_client:
                async with dl_client.stream("GET", download_url) as dl_resp:
                    dl_resp.raise_for_status()
                    total = 0
                    with open(footage_path, "wb") as f:
                        async for chunk in dl_resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            total += len(chunk)
            logger.info(f"[{destination}] Pixabay downloaded {total / (1024*1024):.1f} MB")
            _footage_cache[cache_key] = footage_path
            return footage_path
        except Exception as e:
            logger.error(f"[{destination}] Pixabay download failed: {e}")
            continue

    return None


# ── Text Rendering ──────────────────────────────────────────────────────


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    wrapped = []
    current_line = ""

    for word in words:
        test = f"{current_line} {word}".strip()
        bbox = font.getbbox(test)
        if bbox[2] <= max_width:
            current_line = test
        else:
            if current_line:
                wrapped.append(current_line)
            current_line = word
    if current_line:
        wrapped.append(current_line)

    return wrapped or [text]


def _draw_outlined_text(
    draw: ImageDraw.Draw, pos: tuple, text: str,
    font: ImageFont.FreeTypeFont, fill=(255, 255, 255, 255),
    outline_color=(0, 0, 0, 255), outline_width: int = OUTLINE_WIDTH,
):
    """Draw text with black outline for readability on any background."""
    x, y = pos
    # Draw outline by rendering text in 8 directions
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    # Draw main text on top
    draw.text((x, y), text, font=font, fill=fill)


def render_text_frame(
    lines: list[str],
    visible_count: int,
    trigger_phrase: str,
    brand_color: str,
) -> Image.Image:
    """Render text overlay matching KSO TikTok style.
    Left-aligned, white text with black outline, no background boxes."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _get_font(FONT_SIZE)
    title_font = _get_font(TITLE_FONT_SIZE)

    y = TEXT_Y_START

    for i, text in enumerate(lines[:visible_count]):
        is_title = (i == 0)
        is_cta = trigger_phrase and trigger_phrase.lower() in text.lower()

        active_font = title_font if is_title else font

        # Wrap text into lines that fit
        wrapped = _wrap_text(text, active_font, TEXT_MAX_WIDTH)

        # Draw each wrapped line (left-aligned, outlined)
        for j, line_text in enumerate(wrapped):
            line_y = y + j * LINE_HEIGHT

            if is_cta:
                # CTA text in brand color with white outline
                color_rgb = _hex_to_rgb(brand_color)
                _draw_outlined_text(
                    draw, (TEXT_MARGIN_X, line_y), line_text,
                    font=active_font, fill=(*color_rgb, 255),
                    outline_color=(255, 255, 255, 255), outline_width=2,
                )
            else:
                # Regular white text with black outline
                _draw_outlined_text(
                    draw, (TEXT_MARGIN_X, line_y), line_text,
                    font=active_font,
                )

        block_height = len(wrapped) * LINE_HEIGHT
        y += block_height + BLOCK_SPACING

    return img


# ── Video Composition ───────────────────────────────────────────────────


REMOTION_DIR = Path(__file__).parent.parent / "remotion"


def compose_video(
    brief_id: str,
    script_lines: list[str],
    target_length_seconds: int,
    destination: str,
    comment_trigger_phrase: str,
    footage_path: str | None,
    output_path: str,
    series_title: str = "",
    remotion_template: str = "GreenScreenText",
) -> bool:
    """Compose a single video using Remotion. Returns True on success."""
    import subprocess
    import tempfile

    brand_color = BRAND_COLORS.get(destination, "#FFFFFF")

    # Build props for Remotion
    props = {
        "briefId": brief_id,
        "destination": destination,
        "scriptLines": script_lines,
        "seriesTitle": series_title or f"{destination.title()} Travel Tip",
        "triggerPhrase": comment_trigger_phrase,
        "brandColor": brand_color,
        "footageUrl": "",  # Will be set after copying to public/
        "targetDuration": target_length_seconds,
        "videoFormat": remotion_template,
    }

    # Copy footage to Remotion public/ dir so it can be served
    if footage_path and Path(footage_path).exists():
        import shutil
        public_dir = REMOTION_DIR / "public"
        public_dir.mkdir(exist_ok=True)
        footage_filename = f"{brief_id}_footage.mp4"
        public_footage = public_dir / footage_filename
        shutil.copy2(footage_path, public_footage)
        props["footageUrl"] = f"http://localhost:3000/{footage_filename}"
        # Remotion staticFile() reads from public/
        props["footageUrl"] = footage_filename  # staticFile reference

    # Write props to temp file
    props_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    )
    json.dump(props, props_file)
    props_file.close()

    try:
        # Cap bitrate for longer videos to stay under 50MB Supabase limit
        # 50MB / duration = max bytes/sec, convert to kbps
        max_size_bytes = 48 * 1024 * 1024  # 48MB with margin
        target_bitrate = int((max_size_bytes * 8) / target_length_seconds / 1000)
        target_bitrate = min(target_bitrate, 6000)  # Cap at 6000kbps for quality

        result = subprocess.run(
            [
                "npx", "remotion", "render",
                remotion_template,
                "--output", output_path,
                "--props", props_file.name,
                "--video-bitrate", f"{target_bitrate}K",
            ],
            cwd=str(REMOTION_DIR),
            capture_output=True,
            text=True,
            timeout=120,  # 2 min max per video
        )

        if result.returncode != 0:
            logger.error(f"[{brief_id}] Remotion render failed: {result.stderr[-500:]}")
            return False

        logger.info(f"[{brief_id}] Remotion render complete")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"[{brief_id}] Remotion render timed out")
        return False
    except Exception as e:
        logger.error(f"[{brief_id}] Remotion render error: {e}")
        return False
    finally:
        os.unlink(props_file.name)
        # Clean up footage from Remotion public/
        if footage_path:
            public_footage = REMOTION_DIR / "public" / f"{brief_id}_footage.mp4"
            if public_footage.exists():
                public_footage.unlink()


# ── Supabase Upload ─────────────────────────────────────────────────────


async def upload_to_supabase(file_path: str, brief_id: str, run_date: str) -> str | None:
    """Upload MP4 to Supabase Storage. Returns public URL."""
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL/KEY not set — cannot upload")
        return None

    sb = create_client(url, key)
    storage_path = f"{run_date}/{brief_id}.mp4"

    try:
        with open(file_path, "rb") as f:
            sb.storage.from_("videos").upload(
                storage_path, f.read(), {"content-type": "video/mp4", "upsert": "true"}
            )
        public_url = sb.storage.from_("videos").get_public_url(storage_path)
        return public_url
    except Exception as e:
        logger.error(f"Upload failed for {brief_id}: {e}")
        return None


# ── Load Scripts ────────────────────────────────────────────────────────


def _load_pass_scripts(run_date: date) -> list[dict]:
    """Load scripts that passed audit."""
    audit_file = DATA_DIR / f"audit_results_{run_date.isoformat()}.json"
    if not audit_file.exists():
        logger.error(f"No audit results file: {audit_file}")
        return []
    with open(audit_file) as f:
        audit_data = json.load(f)

    pass_ids = {
        r["brief_id"]
        for r in audit_data.get("results", [])
        if r.get("verdict") == "PASS"
    }
    logger.info(f"Found {len(pass_ids)} PASS verdicts")

    scripts_file = DATA_DIR / f"scripts_{run_date.isoformat()}.json"
    if not scripts_file.exists():
        logger.error(f"No scripts file: {scripts_file}")
        return []
    with open(scripts_file) as f:
        scripts_data = json.load(f)

    pass_scripts = [
        s for s in scripts_data.get("scripts", [])
        if s.get("brief_id") in pass_ids
    ]
    logger.info(f"Matched {len(pass_scripts)} PASS scripts")

    # Load briefs for enrichment
    briefs_file = DATA_DIR / f"briefs_{run_date.isoformat()}.json"
    briefs_map = {}
    if briefs_file.exists():
        with open(briefs_file) as f:
            briefs_data = json.load(f)
        briefs_map = {
            b["brief_id"]: b
            for b in briefs_data.get("briefs", [])
            if "brief_id" in b
        }

    enriched = []
    for script in pass_scripts:
        bid = script.get("brief_id", "")
        brief = briefs_map.get(bid, {})
        series_num = brief.get("series_number")
        dest = brief.get("destination", bid.split("_")[0])
        series_title = f"{dest.title()} Travel Tip #{series_num}" if series_num else ""
        enriched.append({
            "brief_id": bid,
            "destination": dest,
            "topic": brief.get("topic", ""),
            "content_category": brief.get("content_category", ""),
            "script_lines": script.get("script_lines", []),
            "target_length_seconds": script.get("target_length_seconds", 30),
            "comment_trigger_phrase": brief.get("comment_trigger_phrase", ""),
            "video_format": script.get("video_format", "green_screen_text"),
            "series_title": series_title,
            "remotion_template": brief.get("remotion_template", "GreenScreenText"),
        })

    return enriched


# ── Main Build ──────────────────────────────────────────────────────────


async def build_videos(run_date: date, destinations: list[str] | None = None) -> dict:
    """Render videos locally on Mac.

    Args:
        run_date: Date to render videos for
        destinations: Optional list to filter (e.g. ["japan"]). None = all.

    Returns: {"videos": {...}, "stats": {...}}
    """
    logger.info(f"=== Video Builder starting for {run_date} (local Mac render) ===")

    scripts = _load_pass_scripts(run_date)
    if destinations:
        dest_lower = [d.lower() for d in destinations]
        scripts = [s for s in scripts if s["destination"].lower() in dest_lower]

    if not scripts:
        logger.warning("No PASS scripts to render")
        return {"videos": {}, "stats": {"total": 0, "rendered": 0, "failed": 0}}

    logger.info(f"Rendering {len(scripts)} videos locally...")

    tmp_dir = tempfile.mkdtemp(prefix="kso_render_")
    videos = {}
    errors = []

    try:
        for i, script in enumerate(scripts):
            bid = script["brief_id"]
            dest = script["destination"]
            logger.info(f"[{i+1}/{len(scripts)}] {bid}: fetching footage...")

            # Fetch topic-specific footage
            footage_path = await fetch_pexels_footage(
                dest, script["target_length_seconds"], tmp_dir,
                topic=script.get("topic", ""),
                brief_id=bid,
                content_category=script.get("content_category", ""),
            )
            logger.info(f"[{i+1}/{len(scripts)}] {bid}: footage={'OK' if footage_path else 'NONE'}")

            # Compose video
            output_path = os.path.join(tmp_dir, f"{bid}.mp4")
            logger.info(f"[{i+1}/{len(scripts)}] {bid}: composing {script['target_length_seconds']}s video...")

            try:
                success = await asyncio.to_thread(
                    compose_video,
                    bid,
                    script["script_lines"],
                    script["target_length_seconds"],
                    dest,
                    script["comment_trigger_phrase"],
                    footage_path,
                    output_path,
                    series_title=script.get("series_title", ""),
                    remotion_template=script.get("remotion_template", "GreenScreenText"),
                )
            except Exception as e:
                logger.error(f"[{bid}] Compose failed: {e}")
                errors.append({"brief_id": bid, "error": str(e)})
                continue

            if not success:
                errors.append({"brief_id": bid, "error": "Composition returned False"})
                continue

            file_size = os.path.getsize(output_path)
            logger.info(f"[{i+1}/{len(scripts)}] {bid}: rendered ({file_size / (1024*1024):.1f} MB), uploading...")

            # Upload to Supabase
            video_url = await upload_to_supabase(output_path, bid, run_date.isoformat())
            if not video_url:
                errors.append({"brief_id": bid, "error": "Upload failed"})
                continue

            videos[bid] = {
                "url": video_url,
                "duration": script["target_length_seconds"],
            }
            logger.info(f"[{i+1}/{len(scripts)}] {bid}: done!")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    stats = {
        "total": len(scripts),
        "rendered": len(videos),
        "failed": len(errors),
    }

    logger.info(f"Rendered: {stats['rendered']}, Failed: {stats['failed']}")
    for err in errors:
        logger.warning(f"Render error: {err}")

    # Save to Supabase
    video_records = []
    for brief_id, video_data in videos.items():
        dest = brief_id.split("_")[0]
        video_records.append({
            "brief_id": brief_id,
            "date": run_date.isoformat(),
            "destination": dest,
            "video_url": video_data["url"],
            "duration_seconds": video_data.get("duration"),
            "render_status": "rendered",
        })

    if video_records:
        try:
            db.save_rendered_videos(video_records)
        except Exception as e:
            logger.error(f"Failed to save video records to Supabase: {e}")

    # Save to local file
    output_file = DATA_DIR / f"videos_{run_date.isoformat()}.json"
    with open(output_file, "w") as f:
        json.dump({
            "date": run_date.isoformat(),
            "videos": videos,
            "errors": errors,
            "stats": stats,
        }, f, indent=2)

    logger.info(f"=== Video Builder complete: {stats['rendered']} videos ===")
    return {"videos": videos, "stats": stats}
