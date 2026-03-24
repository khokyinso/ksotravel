"""Duplicate topic checker for KSO content pipeline.

Checks against both Supabase published_videos table and local briefs
to ensure no topic is repeated within the dedup window (default 60 days).
"""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from utils import supabase_client as db

# Fallback: check local published.json if Supabase is unavailable
LOGS_DIR = Path(__file__).parent.parent / "logs"
PUBLISHED_LOG = LOGS_DIR / "published.json"


def _normalize(topic: str) -> str:
    """Normalize topic for comparison — lowercase, strip extra whitespace."""
    return " ".join(topic.lower().strip().split())


def _similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity between two topic strings."""
    words_a = set(_normalize(a).split())
    words_b = set(_normalize(b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / min(len(words_a), len(words_b))


def get_recent_topics_from_db(destination: str, days: int = 60) -> list[str]:
    """Fetch recently published topics from Supabase."""
    try:
        return db.get_recent_topics(destination, days)
    except Exception as e:
        logger.warning(f"Supabase unavailable for dedup check: {e}")
        return []


def get_recent_topics_from_local(destination: str, days: int = 60) -> list[str]:
    """Fetch recently published topics from local published.json fallback."""
    if not PUBLISHED_LOG.exists():
        return []

    try:
        with open(PUBLISHED_LOG) as f:
            records = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return [
        r["topic"]
        for r in records
        if r.get("destination") == destination
        and r.get("published_at", "") >= cutoff
    ]


def get_recent_topics(destination: str, days: int = 60) -> list[str]:
    """Get all recent topics from both DB and local sources."""
    topics = get_recent_topics_from_db(destination, days)
    local_topics = get_recent_topics_from_local(destination, days)

    # Merge and deduplicate
    seen = set()
    merged = []
    for t in topics + local_topics:
        norm = _normalize(t)
        if norm not in seen:
            seen.add(norm)
            merged.append(t)
    return merged


def is_duplicate(
    topic: str,
    destination: str,
    recent_topics: list[str] | None = None,
    threshold: float = 0.7,
) -> bool:
    """Check if a topic is a duplicate of any recently published topic.

    Args:
        topic: The candidate topic to check.
        destination: Destination channel.
        recent_topics: Pre-fetched list of recent topics. If None, fetches from DB.
        threshold: Similarity threshold (0-1). Default 0.7 catches near-duplicates.

    Returns:
        True if the topic is considered a duplicate.
    """
    if recent_topics is None:
        recent_topics = get_recent_topics(destination)

    norm_topic = _normalize(topic)
    for existing in recent_topics:
        norm_existing = _normalize(existing)
        # Exact match
        if norm_topic == norm_existing:
            logger.debug(f"Exact duplicate: '{topic}' matches '{existing}'")
            return True
        # Fuzzy match
        if _similarity(topic, existing) >= threshold:
            logger.debug(
                f"Near duplicate: '{topic}' ~ '{existing}' "
                f"(similarity={_similarity(topic, existing):.2f})"
            )
            return True
    return False


def filter_duplicates(
    topics: list[dict],
    destination: str,
    topic_key: str = "topic",
) -> list[dict]:
    """Filter out duplicate topics from a list.

    Args:
        topics: List of dicts containing topic information.
        destination: Destination channel.
        topic_key: Key in each dict that contains the topic string.

    Returns:
        Filtered list with duplicates removed.
    """
    recent = get_recent_topics(destination)
    filtered = []
    # Also track within-batch duplicates
    batch_topics: list[str] = []

    for item in topics:
        topic = item.get(topic_key, "")
        if is_duplicate(topic, destination, recent_topics=recent + batch_topics):
            logger.info(f"Filtered duplicate topic for {destination}: '{topic}'")
            continue
        filtered.append(item)
        batch_topics.append(topic)

    removed = len(topics) - len(filtered)
    if removed:
        logger.info(f"Removed {removed} duplicates for {destination}")
    return filtered
