# 04 — DM Engine (Hybrid)
> Agents 10–11 | ManyChat Starter (TikTok) + Native Meta API (Instagram)

---

## Why Hybrid Architecture

TikTok and Instagram have different API capabilities for comment-to-DM:

| Platform | Native Comment→DM API | Our Approach | Cost |
|---|---|---|---|
| **Instagram** | ✅ Full support | Meta Webhooks + Graph API | Free |
| **TikTok** | ⚠️ Beta, US not supported | ManyChat Starter (detection only) | $15–45/mo |

**ManyChat Starter does ONE thing: detects keywords in TikTok comments and fires a webhook.**
All intelligence — DM content, sequencing, opt-outs, analytics — lives in your code.

```
TIKTOK:
Comment → [ManyChat Starter detects keyword]
        → POST /webhook/tiktok/trigger
        → Agent 10 → spam filter → Agent 11
        → TikTok Business Messaging API → DM sent ✅

INSTAGRAM (fully native, zero ManyChat):
Comment → [Meta Webhook fires automatically]
        → POST /webhook/instagram/comments
        → Agent 10 → keyword check → spam filter → Agent 11
        → Meta Graph API → DM sent ✅
```

---

## Webhook Server

**File:** `railway/webhook_server.py`
**Runs on:** Railway (always-on, tiny instance ~$5/mo)
**Framework:** FastAPI

The webhook server runs 24/7 on Railway because it needs to respond instantly to
incoming comment events. The Mac runs the DM generation and sending.

```python
from fastapi import FastAPI, Request
import os, httpx

app = FastAPI()


# ── TIKTOK (via ManyChat Starter) ──────────────────────────────────────────
@app.post("/webhook/tiktok/trigger")
async def tiktok_trigger(request: Request):
    """
    ManyChat Starter fires this when a TikTok comment matches a keyword.
    Payload includes keyword, username, and our custom fields set during registration.
    """
    payload = await request.json()

    context = {
        "platform": "tiktok",
        "username": payload["subscriber"]["username"],
        "trigger_phrase": payload["keyword"],
        "post_id": payload.get("post_id"),
        "topic": payload["custom_fields"].get("topic"),
        "destination": payload["custom_fields"].get("destination"),
        "category": payload["custom_fields"].get("category"),
        "deal_url": payload["custom_fields"].get("deal_url"),
        "deal_platform": payload["custom_fields"].get("deal_platform")
    }

    result = await process_trigger(context)
    return {"status": "ok", "action": result}


# ── INSTAGRAM (fully native) ────────────────────────────────────────────────
@app.post("/webhook/instagram/comments")
async def instagram_comment(request: Request):
    """
    Meta Webhooks fires this on every new comment on subscribed posts.
    We detect the keyword ourselves — no ManyChat involved.
    """
    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change["field"] == "comments":
                data = change["value"]
                comment_text = data.get("text", "")
                post_id = data.get("media", {}).get("id")
                user_id = data.get("from", {}).get("id")
                username = data.get("from", {}).get("name")

                trigger = await detect_trigger(comment_text, post_id)
                if trigger:
                    video_ctx = await get_video_context(post_id)
                    context = {
                        "platform": "instagram",
                        "username": username,
                        "user_id": user_id,
                        "trigger_phrase": trigger,
                        "post_id": post_id,
                        **video_ctx
                    }
                    await process_trigger(context)

    return {"status": "ok"}


# ── META WEBHOOK VERIFICATION (required one-time setup) ────────────────────
@app.get("/webhook/instagram/comments")
async def verify_meta_webhook(hub_mode: str, hub_verify_token: str, hub_challenge: str):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("META_WEBHOOK_VERIFY_TOKEN"):
        return int(hub_challenge)
    return {"error": "Forbidden"}, 403
```

---

## Agent 10: Comment Trigger Monitor

**File:** `agents/comment_trigger_monitor.py`
**Model:** Claude Haiku 4.5 (spam classification only)
**Runs on:** Called by webhook server (Railway) → executes on Mac via internal queue

### Job
1. Receive trigger context from webhook server
2. Run spam/bot filter
3. If genuine → post public comment reply → trigger Agent 11
4. If spam → log + discard

### Trigger Detection (Instagram — our own logic)

```python
# utils/trigger_detector.py
from supabase_client import supabase

async def detect_trigger(comment_text: str, post_id: str) -> str | None:
    """
    Check if comment contains a registered trigger phrase for this post.
    Returns matched trigger phrase or None.
    """
    result = await supabase.table("post_triggers") \
        .select("trigger_phrase") \
        .eq("post_id", post_id) \
        .execute()

    comment_upper = comment_text.upper().strip()
    for row in result.data:
        if row["trigger_phrase"].upper() in comment_upper:
            return row["trigger_phrase"]
    return None
```

### Spam / Bot Filter

```python
# utils/spam_detector.py

async def is_spam(platform: str, username: str, comment_text: str) -> tuple[bool, str]:
    """Returns (is_spam, reason)"""

    # Rule 1: Account 0 posts + 0 followers → bot
    profile = await get_profile(platform, username)
    if profile.posts == 0 and profile.followers == 0:
        return True, "zero_activity_account"

    # Rule 2: Same trigger on 5+ posts in 1 hour → spam
    recent = await supabase.table("dm_log") \
        .select("id") \
        .eq("username", username) \
        .gte("sent_at", one_hour_ago()) \
        .execute()
    if len(recent.data) >= 5:
        return True, "spam_flood"

    # Rule 3: External links in comment → spam
    if "http" in comment_text.lower() or "www." in comment_text.lower():
        return True, "external_link"

    # Rule 4: Account < 7 days old → soft flag (log, still send DM)
    if profile.account_age_days < 7:
        await log_soft_flag(username, "new_account")
        return False, "soft_flag_new_account"  # Still process

    # Rule 5: Prompt injection → block
    from prompt_injection_guard import is_injection
    if is_injection(comment_text):
        await log_injection(username, comment_text)
        return True, "prompt_injection"

    return False, "clean"
```

### Public Comment Reply (both platforms)
After spam filter passes, immediately post public reply:
```python
public_reply = "✅ Just sent you a DM! Make sure your DMs are open 🙏"
await post_comment_reply(platform, post_id, comment_id, public_reply)
```
This reply itself drives more people to comment the trigger phrase.

### Context Payload to Agent 11
```json
{
  "username": "@user123",
  "user_id": "12345",
  "platform": "instagram",
  "post_id": "abc123",
  "trigger_phrase": "PARIS STAY",
  "topic": "Best Paris neighborhoods under $150",
  "destination": "france",
  "category": "accommodation",
  "deal_url": "https://booking.com/...",
  "deal_platform": "booking"
}
```

---

## Agent 11: DM Funnel Sender

**File:** `agents/dm_funnel_sender.py`
**Model:** Claude Sonnet 4.6
**Runs on:** Mac (triggered by Agent 10 via internal queue)

### Job
Generate AI-personalized DM based on video context.
Send via platform-native APIs.
Schedule Message 2 in Supabase (24h later).

### DM Platform Routing

```python
# utils/dm_client.py

async def send_dm(platform: str, user_id: str, message: str) -> bool:

    if platform == "tiktok":
        resp = await httpx.post(
            "https://business-api.tiktok.com/open_api/v1.3/business/message/send/",
            headers={"Access-Token": os.getenv("TIKTOK_BUSINESS_ACCESS_TOKEN")},
            json={
                "business_id": os.getenv("TIKTOK_BUSINESS_ID"),
                "recipient_id": user_id,
                "message_type": "TEXT",
                "content": {"text": message}
            }
        )
        return resp.json().get("code") == 0

    elif platform == "instagram":
        resp = await httpx.post(
            f"https://graph.facebook.com/v19.0/{os.getenv('INSTAGRAM_ACCOUNT_ID')}/messages",
            headers={"Authorization": f"Bearer {os.getenv('META_ACCESS_TOKEN')}"},
            json={
                "recipient": {"id": user_id},
                "message": {"text": message}
            }
        )
        return resp.status_code == 200
```

### DM Content by Video Category

| Category | Message Content | Affiliate Link |
|---|---|---|
| `transport` | Rail/transport guide + booking tips | Klook/GYG transport pass |
| `food_tour` | Restaurant list + food tour | GYG/Viator food tour |
| `accommodation` | Neighborhood guide + hotel deals | Booking.com |
| `attraction` | Skip-line tips + ticket link | Klook/Viator attraction |
| `experience` | Experience breakdown + booking | GYG/Viator |
| `visa_entry` | Step-by-step visa guide | Viator/Klook tours |
| `timing` | Best/worst dates + seasonal deal | Best seasonal deal |
| `day_trip` | Day trip guide + booking | GYG/Viator day trip |

### Message 1 Template (sent immediately)
```
Hey [username]! 👋 Here's your [destination] [topic] breakdown 👇

• [Specific tip 1 — real detail from video]
• [Specific tip 2 — bonus not in video]
• [Specific tip 3 — money-saving angle]

🔗 Full booking details: [affiliate link]
Use code KSOTRAVEL for 10% off

Reply STOP to unsubscribe
```

### Message 2 Template (sent 24h later — only if no reply)
```
One more [destination] tip you'll want to know before you go...

[1 bonus tip directly related to their video category]

🔗 [secondary affiliate link — different product, same category]

Reply STOP to unsubscribe
```

### Hard Limits
- Max 2 DMs per user per 24 hours across ALL 12 channels combined
- Message 2 = maximum sequence depth. No further follow-up ever.
- Check opt-out before every send
- Never DM users who haven't commented first

### Opt-Out System

```python
# Check before every DM
async def is_opted_out(username: str, platform: str) -> bool:
    result = await supabase.table("dm_subscribers") \
        .select("opted_out") \
        .eq("username", username) \
        .eq("platform", platform) \
        .maybe_single() \
        .execute()
    return bool(result.data and result.data.get("opted_out"))


# Handle STOP reply
async def handle_reply(platform: str, username: str, message_text: str):
    if "STOP" in message_text.upper():
        await supabase.table("dm_subscribers").upsert({
            "username": username,
            "platform": platform,
            "opted_out": True,
            "opted_out_at": datetime.utcnow().isoformat()
        }).execute()
        await dm_client.send_dm(
            platform, username,
            "You've been unsubscribed from KSO messages. You won't hear from us again 👋"
        )
```

### Message 2 Scheduling (Supabase)
```python
# After sending Message 1, schedule Message 2
await supabase.table("dm_subscribers").upsert({
    "username": username,
    "platform": platform,
    "message_1_sent_at": now(),
    "message_2_send_at": now() + timedelta(hours=24),
    "last_destination": destination,
    "last_topic": topic
}).execute()
```

A separate cron job (`agents/dm_sequence_runner.py`) runs every 15 minutes,
checks for pending Message 2s, and sends them if due and user hasn't opted out.

---

## Supabase Tables (DM Engine)

```sql
-- Trigger phrase registry (both platforms)
CREATE TABLE post_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    trigger_phrase TEXT NOT NULL,
    destination TEXT,
    channel TEXT,
    topic TEXT,
    category TEXT,
    deal_url TEXT,
    deal_platform TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_post_triggers_post_id ON post_triggers(post_id);

-- Subscriber management + opt-outs
CREATE TABLE dm_subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL,
    user_id TEXT,
    platform TEXT NOT NULL,
    opted_out BOOLEAN DEFAULT FALSE,
    opted_out_at TIMESTAMP,
    message_1_sent_at TIMESTAMP,
    message_2_send_at TIMESTAMP,
    message_2_sent_at TIMESTAMP,
    last_destination TEXT,
    last_topic TEXT,
    total_clicks INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(username, platform)
);

-- DM send log
CREATE TABLE dm_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT,
    platform TEXT,
    channel TEXT,
    destination TEXT,
    category TEXT,
    message_number INTEGER,
    affiliate_url TEXT,
    opened BOOLEAN DEFAULT FALSE,
    clicked BOOLEAN DEFAULT FALSE,
    converted BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_dm_log_username ON dm_log(username, sent_at);
```

---

## ManyChat Starter Setup

ManyChat Starter is used ONLY for TikTok keyword detection.

### What to configure in ManyChat dashboard:
1. Connect your 12 TikTok business accounts
2. Set webhook URL: `https://your-app.up.railway.app/webhook/tiktok/trigger`
3. Enable keyword trigger mode (not flow mode — we handle everything)

### What Agent 9 does when publishing a TikTok:
```python
# Register the trigger phrase for this specific post
manychat_client.register_keyword(
    tiktok_account_id=channel_config["manychat_page_id"],
    post_id=tiktok_post_id,
    keyword=brief.comment_trigger_phrase,
    webhook_url=os.getenv("MANYCHAT_WEBHOOK_URL"),
    custom_fields={
        "topic": brief.topic,
        "destination": brief.destination,
        "category": brief.content_category,
        "deal_url": brief.deal.url,
        "deal_platform": brief.deal.platform
    }
)
```

### ManyChat does NOT:
- Generate any DM content
- Send any messages
- Track any analytics
- Manage any subscriber data
Everything above lives in your code + Supabase.

---

## Daily DM Metrics (logged by Agent 15)

```
Total DMs sent today: 1,247
  TikTok: 687 (via ManyChat trigger → your code)
  Instagram: 560 (fully native)

Message 1 delivery rate: 94%
Message 2 send rate: 61% (of M1 recipients, after 24h)
DM open rate: 71%
Affiliate click rate from DMs: 35%
Opt-out rate: 0.8%

Best performing channel DMs: KSO.Japan (42% click rate)
Best performing category: transport guides (48% click rate)
```
