"""Shared constants for KSO Travel Automation.

Single source of truth for destinations, video formats, hook angles,
and other values used across multiple agents.
"""

DESTINATIONS = [
    "japan", "greece", "italy", "korea", "thailand", "mexico",
    "portugal", "spain", "france", "turkey", "poland", "china",
]

VIDEO_FORMATS = [
    "green_screen_text",      # Text overlay on stock footage (KSO default)
    "pov_walking",            # POV walking tour / first person
    "split_screen",           # Side-by-side comparison
    "photo_slideshow",        # Photo slideshow with voiceover
    "series_part",            # "Part 1/2/3" series hook
    "stitch_reaction",        # Stitch/duet reaction to another creator
    "map_zoom",               # Map zoom-in transition to location
    "before_after",           # Expectation vs reality reveal
    "countdown_list",         # Countdown listicle (5, 4, 3, 2, 1)
    "storytime",              # Personal story with text captions
]

HOOK_ANGLES = [
    "warning", "hack", "secret", "timing",
    "comparison", "listicle", "story", "reaction",
]

DEAL_CATEGORIES = [
    "transport", "attraction", "food_tour", "accommodation",
    "experience", "day_trip", "guided_tour",
]

# Platform affiliate commission rates
PLATFORM_COMMISSIONS = {
    "klook": {"min": 0.05, "max": 0.08, "cookie_days": 30},
    "gyg": {"min": 0.08, "max": 0.08, "cookie_days": 30},
    "viator": {"min": 0.08, "max": 0.08, "cookie_days": 30},
    "booking": {"min": 0.04, "max": 0.06, "cookie_days": 0},
    "cj": {"min": 0.03, "max": 0.10, "cookie_days": 7},
}

# Platform priority per destination (which affiliate to prefer)
PLATFORM_PRIORITY = {
    "japan": ["klook", "viator", "gyg"],
    "greece": ["gyg", "viator", "klook"],
    "italy": ["viator", "gyg", "booking"],
    "korea": ["klook", "gyg", "viator"],
    "thailand": ["gyg", "klook", "viator"],
    "mexico": ["viator", "gyg", "klook"],
    "portugal": ["booking", "gyg", "viator"],
    "spain": ["gyg", "viator", "booking"],
    "france": ["gyg", "booking", "viator"],
    "turkey": ["klook", "gyg", "viator"],
    "poland": ["gyg", "booking", "viator"],
    "china": ["viator", "klook", "gyg"],
}

# Target line counts by video length
TARGET_LINE_COUNTS = {
    15: 5,
    30: 7,
    45: 10,
    60: 10,
}
