"""Token usage tracker for all Anthropic API calls.

Wraps client.messages.create() to capture usage, calculate cost,
store in Supabase, and alert on overspend via Telegram.
"""

import os
from datetime import date, datetime
from typing import Any

import anthropic
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

# Pricing per million tokens (USD)
MODEL_PRICING = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

# Module-level singleton client
_client: anthropic.Anthropic | None = None

# Session-level accumulator
_session_totals: dict[str, dict] = {}


def _get_client() -> anthropic.Anthropic:
    """Get or create the Anthropic client singleton."""
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a given model and token counts."""
    pricing = MODEL_PRICING.get(model, {"input": 3.00, "output": 15.00})
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


def _accumulate(agent_name: str, usage_record: dict) -> None:
    """Add usage to session totals."""
    if agent_name not in _session_totals:
        _session_totals[agent_name] = {
            "calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
        }
    totals = _session_totals[agent_name]
    totals["calls"] += 1
    totals["input_tokens"] += usage_record["input_tokens"]
    totals["output_tokens"] += usage_record["output_tokens"]
    totals["cost_usd"] += usage_record["cost_usd"]


def _save_to_supabase(usage_record: dict) -> None:
    """Fire-and-forget save to Supabase. Never raises."""
    try:
        from utils import supabase_client as db
        db.save_usage_log(usage_record)
    except Exception as e:
        logger.debug(f"Failed to save usage log to Supabase: {e}")


def tracked_create(
    model: str,
    max_tokens: int,
    messages: list[dict],
    system: str | list | None = None,
    agent_name: str = "unknown",
    context: dict | None = None,
) -> tuple[str, dict]:
    """Wrapper around client.messages.create() that tracks token usage.

    Returns:
        tuple of (response_text, usage_record)
    """
    client = _get_client()

    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)

    text = response.content[0].text
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost_usd = _calculate_cost(model, input_tokens, output_tokens)

    usage_record = {
        "date": date.today().isoformat(),
        "agent_name": agent_name,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "context": context or {},
    }

    _accumulate(agent_name, usage_record)
    _save_to_supabase(usage_record)

    logger.debug(
        f"[{agent_name}] {model}: {input_tokens}in/{output_tokens}out = ${cost_usd:.4f}"
    )

    return text, usage_record


def get_session_summary() -> dict:
    """Return accumulated session totals by agent."""
    total_cost = sum(a["cost_usd"] for a in _session_totals.values())
    total_input = sum(a["input_tokens"] for a in _session_totals.values())
    total_output = sum(a["output_tokens"] for a in _session_totals.values())
    total_calls = sum(a["calls"] for a in _session_totals.values())

    return {
        "by_agent": dict(_session_totals),
        "total_cost_usd": round(total_cost, 4),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_calls": total_calls,
    }


def reset_session() -> None:
    """Reset session totals (for testing or between pipeline runs)."""
    _session_totals.clear()


def check_cost_alert(threshold_usd: float | None = None) -> bool:
    """Check if daily cost exceeds threshold. Send Telegram alert if so.

    Returns True if alert was triggered.
    """
    if threshold_usd is None:
        threshold_usd = float(os.getenv("DAILY_COST_ALERT_USD", "5.00"))

    summary = get_session_summary()
    total = summary["total_cost_usd"]

    if total < threshold_usd:
        return False

    message = (
        f"⚠️ KSO Travel API Cost Alert\n\n"
        f"Daily spend: ${total:.2f} (threshold: ${threshold_usd:.2f})\n"
        f"Total calls: {summary['total_calls']}\n\n"
    )
    for agent, data in summary["by_agent"].items():
        message += f"  {agent}: ${data['cost_usd']:.4f} ({data['calls']} calls)\n"

    _send_telegram_alert(message)
    return True


def _send_telegram_alert(message: str) -> None:
    """Send alert via Telegram bot. Silently fails if not configured."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning(f"Telegram not configured — cost alert: {message}")
        return

    try:
        import httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        httpx.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        logger.info("Cost alert sent via Telegram")
    except Exception as e:
        logger.warning(f"Failed to send Telegram alert: {e}")
