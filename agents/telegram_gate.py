"""Agent 8: Telegram Review Gate

Sends sample videos to Telegram for human approval.
Approving a channel auto-approves all videos for that channel.
Auto-approves after 90-minute timeout.

Model: None (no AI calls)
Schedule: After video rendering completes
"""

import asyncio
import os
import time
from datetime import date

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

# Channel emojis for Telegram messages
CHANNEL_EMOJIS = {
    "japan": "\U0001F1EF\U0001F1F5", "greece": "\U0001F1EC\U0001F1F7",
    "italy": "\U0001F1EE\U0001F1F9", "korea": "\U0001F1F0\U0001F1F7",
    "thailand": "\U0001F1F9\U0001F1ED", "mexico": "\U0001F1F2\U0001F1FD",
    "portugal": "\U0001F1F5\U0001F1F9", "spain": "\U0001F1EA\U0001F1F8",
    "france": "\U0001F1EB\U0001F1F7", "turkey": "\U0001F1F9\U0001F1F7",
    "poland": "\U0001F1F5\U0001F1F1", "china": "\U0001F1E8\U0001F1F3",
}


def _get_bot_config() -> tuple[str, str] | None:
    """Get Telegram bot token and chat ID."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return None
    return token, chat_id


async def _send_sample(
    token: str,
    chat_id: str,
    destination: str,
    video_url: str,
    brief_id: str,
    topic: str = "",
) -> int | None:
    """Send a sample video to Telegram with approve/reject buttons.

    Returns message_id on success, None on failure.
    """
    emoji = CHANNEL_EMOJIS.get(destination, "")
    caption = (
        f"{emoji} @kso.{destination}\n"
        f"Brief: {brief_id}\n"
        f"Topic: {topic}\n\n"
        f"Reply with buttons below:"
    )

    reply_markup = {
        "inline_keyboard": [[
            {"text": "APPROVE", "callback_data": f"approve_{destination}"},
            {"text": "REJECT", "callback_data": f"reject_{destination}"},
        ]]
    }

    url = f"https://api.telegram.org/bot{token}/sendVideo"
    payload = {
        "chat_id": chat_id,
        "video": video_url,
        "caption": caption,
        "reply_markup": reply_markup,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if data.get("ok"):
                return data["result"]["message_id"]
            else:
                # If video URL fails, try sending as text with link
                logger.warning(f"sendVideo failed for {destination}, trying text message")
                text_url = f"https://api.telegram.org/bot{token}/sendMessage"
                text_payload = {
                    "chat_id": chat_id,
                    "text": f"{caption}\n\nVideo: {video_url}",
                    "reply_markup": reply_markup,
                }
                resp2 = await client.post(text_url, json=text_payload)
                data2 = resp2.json()
                if data2.get("ok"):
                    return data2["result"]["message_id"]
    except Exception as e:
        logger.error(f"Failed to send sample for {destination}: {e}")

    return None


async def _poll_responses(
    token: str,
    destinations: set[str],
    timeout_minutes: int = 90,
) -> dict[str, str]:
    """Poll for callback_query responses.

    Returns dict mapping destination -> "approve" or "reject".
    """
    timeout_sec = timeout_minutes * 60
    start = time.time()
    responses: dict[str, str] = {}
    last_update_id = 0

    # Clear any old updates first
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": -1, "limit": 1},
            )
            data = resp.json()
            updates = data.get("result", [])
            if updates:
                last_update_id = updates[-1]["update_id"] + 1
    except Exception:
        pass

    while time.time() - start < timeout_sec:
        remaining = set(destinations) - set(responses.keys())
        if not remaining:
            break

        try:
            async with httpx.AsyncClient(timeout=35) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={
                        "offset": last_update_id,
                        "timeout": 30,
                        "allowed_updates": '["callback_query"]',
                    },
                )
                data = resp.json()
        except Exception:
            await asyncio.sleep(5)
            continue

        for update in data.get("result", []):
            last_update_id = update["update_id"] + 1

            callback = update.get("callback_query")
            if not callback:
                continue

            callback_data = callback.get("data", "")
            callback_id = callback.get("id", "")

            # Parse: "approve_japan" or "reject_japan"
            if "_" not in callback_data:
                continue

            action, dest = callback_data.split("_", 1)
            if dest in destinations and action in ("approve", "reject"):
                responses[dest] = action
                logger.info(f"Telegram: {dest} -> {action.upper()}")

                # Answer callback to remove loading state
                try:
                    async with httpx.AsyncClient(timeout=5) as client:
                        await client.post(
                            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                            json={
                                "callback_query_id": callback_id,
                                "text": f"{dest.title()} {action}d!",
                            },
                        )
                except Exception:
                    pass

    return responses


async def run(
    sample_videos: dict[str, dict],
    briefs_map: dict[str, dict] | None = None,
    timeout_minutes: int | None = None,
) -> dict:
    """Run Telegram review gate.

    Args:
        sample_videos: {destination: {"url": "...", "brief_id": "..."}}
        briefs_map: {brief_id: brief_dict} for topic info
        timeout_minutes: Override default 90-min timeout

    Returns:
        {"approved": [...], "rejected": [...], "auto_approved": [...]}
    """
    if timeout_minutes is None:
        timeout_minutes = int(os.getenv("TELEGRAM_AUTO_APPROVE_TIMEOUT_MIN", "90"))

    logger.info(f"=== Telegram Gate starting ({len(sample_videos)} samples) ===")

    config = _get_bot_config()
    if not config:
        logger.warning("Telegram not configured — auto-approving all")
        return {
            "approved": list(sample_videos.keys()),
            "rejected": [],
            "auto_approved": list(sample_videos.keys()),
        }

    token, chat_id = config

    # Send notification header
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": (
                        f"KSO Travel — Video Review\n"
                        f"{len(sample_videos)} channels ready for review.\n"
                        f"Auto-approve in {timeout_minutes} min if no response."
                    ),
                },
            )
    except Exception:
        pass

    # Send samples
    destinations = set()
    for dest, video_info in sample_videos.items():
        brief_id = video_info.get("brief_id", "")
        video_url = video_info.get("url", "")
        topic = ""
        if briefs_map and brief_id in briefs_map:
            topic = briefs_map[brief_id].get("topic", "")

        msg_id = await _send_sample(token, chat_id, dest, video_url, brief_id, topic)
        if msg_id:
            destinations.add(dest)
            logger.info(f"Sent sample for {dest} (msg_id={msg_id})")
        else:
            logger.warning(f"Failed to send sample for {dest} — auto-approving")

    if not destinations:
        logger.warning("No samples sent — auto-approving all")
        return {
            "approved": list(sample_videos.keys()),
            "rejected": [],
            "auto_approved": list(sample_videos.keys()),
        }

    # Poll for responses
    logger.info(f"Waiting for Telegram responses (timeout: {timeout_minutes} min)...")
    responses = await _poll_responses(token, destinations, timeout_minutes)

    # Categorize results
    approved = [d for d, a in responses.items() if a == "approve"]
    rejected = [d for d, a in responses.items() if a == "reject"]
    no_response = destinations - set(responses.keys())
    auto_approved = list(no_response)  # No response = auto-approve

    all_approved = approved + auto_approved

    result = {
        "approved": all_approved,
        "rejected": rejected,
        "auto_approved": auto_approved,
        "explicit_approved": approved,
    }

    logger.info(
        f"=== Telegram Gate complete: "
        f"{len(all_approved)} approved, {len(rejected)} rejected, "
        f"{len(auto_approved)} auto-approved ==="
    )

    return result
