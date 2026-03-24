# 09 — Railway Setup
> Two services: Video Builder (Agent 7) + Webhook Server (Agents 10, 12)

---

## Why Railway

Two components run on Railway instead of Mac:

| Service | Why Railway | Cost |
|---|---|---|
| Video Builder | 96 parallel MP4 renders would thermal throttle fanless Mac | ~$20/mo |
| Webhook Server | Needs to be always-on, 24/7 to receive comment events | ~$5/mo |

MacBook Air can render videos locally in `local_safe` mode (4 at a time, overnight)
if you want to delay Railway setup, but Railway is recommended for daily production.

---

## Railway Installation

```bash
# Install Railway CLI
brew install railway

# Login
railway login
# Opens browser to authenticate

# Verify
railway --version
```

---

## Service 1: Video Builder

**File:** `railway/video_builder_service.py`
**Purpose:** Receives render job from Mac, renders 96 MP4s in parallel, returns URLs

### Deploy

```bash
cd kso-travel-automation

# Initialize Railway project
railway init
# Select: Empty project
# Name: kso-video-builder

# Link to Railway project
railway link

# Set environment variables on Railway
railway variables set PEXELS_API_KEY=your_key
railway variables set SUPABASE_URL=your_url
railway variables set SUPABASE_KEY=your_key
railway variables set RUNWAY_API_KEY=your_key  # For AI B-roll fallback

# Deploy
railway up
```

### railway/video_builder_service.py

```python
"""
Video Builder Service — runs on Railway cloud.
Receives render jobs from Mac orchestrator.
Renders all videos in parallel, uploads to Supabase Storage, returns URLs.
"""
from fastapi import FastAPI
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, AudioFileClip
from PIL import Image, ImageDraw, ImageFont
import asyncio, os, httpx
from supabase import create_client

app = FastAPI()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

@app.post("/render")
async def render_job(payload: dict):
    """
    Receives list of approved scripts.
    Renders all MP4s in parallel.
    Uploads to Supabase Storage.
    Returns dict of {brief_id: mp4_url}.
    """
    scripts = payload["scripts"]

    # Render all in parallel
    tasks = [render_single(script) for script in scripts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    urls = {}
    for script, result in zip(scripts, results):
        if isinstance(result, Exception):
            urls[script["brief_id"]] = {"error": str(result)}
        else:
            urls[script["brief_id"]] = {"url": result}

    return {"status": "complete", "videos": urls}


async def render_single(script: dict) -> str:
    """Render one video and return Supabase Storage URL."""
    brief_id = script["brief_id"]
    destination = script["destination"]
    lines = script["script_lines"]
    length_s = script["target_length_seconds"]
    trigger_phrase = script["comment_trigger_phrase"]
    brand_color = BRAND_COLORS[destination]

    # 1. Get background footage
    footage_path = await get_footage(destination, script["content_category"])

    # 2. Build text overlay frames
    overlay = build_text_overlay(lines, trigger_phrase, brand_color, length_s)

    # 3. Get music
    music_path = get_music(destination)

    # 4. Composite video
    output_path = f"/tmp/{brief_id}.mp4"
    compose_video(footage_path, overlay, music_path, output_path, length_s)

    # 5. Upload to Supabase Storage
    with open(output_path, "rb") as f:
        supabase.storage.from_("videos").upload(
            path=f"{brief_id}.mp4",
            file=f,
            file_options={"content-type": "video/mp4"}
        )

    # 6. Get public URL
    url = supabase.storage.from_("videos").get_public_url(f"{brief_id}.mp4")
    return url


BRAND_COLORS = {
    "japan": "#E8272A", "korea": "#00A693", "france": "#002395",
    "italy": "#009246", "greece": "#0D5EAF", "turkey": "#E30A17",
    "thailand": "#F5C518", "mexico": "#006847", "portugal": "#006600",
    "spain": "#AA151B", "poland": "#DC143C", "china": "#DE2910"
}
```

### Mac Stub — How Mac Triggers Railway

```python
# agents/video_builder.py (runs on Mac)

import httpx, os

RAILWAY_VIDEO_URL = os.getenv("RAILWAY_VIDEO_SERVICE_URL")

async def build_videos(approved_scripts: list) -> dict:
    if os.getenv("VIDEO_RENDER_MODE") == "local_safe":
        return await render_local_batched(approved_scripts, batch_size=4)

    # Default: submit to Railway
    async with httpx.AsyncClient(timeout=1800) as client:  # 30 min timeout
        response = await client.post(
            f"{RAILWAY_VIDEO_URL}/render",
            json={"scripts": approved_scripts}
        )
        return response.json()["videos"]
```

Add to `.env`:
```bash
RAILWAY_VIDEO_SERVICE_URL=https://kso-video-builder.up.railway.app
VIDEO_RENDER_MODE=railway
```

---

## Service 2: Webhook Server

**File:** `railway/webhook_server.py`
**Purpose:** Always-on FastAPI that receives TikTok (ManyChat) and Instagram (Meta) comment events

### Deploy as Separate Railway Service

```bash
# Create second Railway service
railway init
# Select: Empty project
# Name: kso-webhook-server

railway link

# Set env vars
railway variables set SUPABASE_URL=your_url
railway variables set SUPABASE_KEY=your_key
railway variables set META_WEBHOOK_VERIFY_TOKEN=your_chosen_secret
railway variables set MAC_AGENT_URL=http://your-mac-ngrok-url  # see note below

railway up
```

### Connecting Webhook Server Back to Mac

The webhook server on Railway needs to call Agent 10/11 on your Mac.
Two options:

**Option A: ngrok (development/testing)**
```bash
# Install ngrok
brew install ngrok

# Expose your Mac's port 8001
ngrok http 8001

# Copy the ngrok URL (e.g. https://abc123.ngrok.io)
# Set on Railway:
railway variables set MAC_AGENT_URL=https://abc123.ngrok.io
```

**Option B: VPS (production — recommended)**
Run Agent 10/11 on a cheap $6/mo DigitalOcean droplet instead of Mac.
More reliable, no ngrok dependency.
```bash
# On DigitalOcean Ubuntu droplet:
pip install anthropic fastapi uvicorn supabase python-dotenv
# Deploy agents 10, 11 as FastAPI endpoints
# Set MAC_AGENT_URL to your droplet's IP
```

### railway/webhook_server.py (full)

```python
from fastapi import FastAPI, Request
import os, httpx
from supabase import create_client

app = FastAPI()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
MAC_AGENT_URL = os.getenv("MAC_AGENT_URL")


# ── TIKTOK: ManyChat Starter fires this ─────────────────────────────────
@app.post("/webhook/tiktok/trigger")
async def tiktok_trigger(request: Request):
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
    # Forward to Mac Agent 10
    async with httpx.AsyncClient() as client:
        await client.post(f"{MAC_AGENT_URL}/agent10/process", json=context)
    return {"status": "ok"}


# ── INSTAGRAM: Meta Webhooks fires this ─────────────────────────────────
@app.post("/webhook/instagram/comments")
async def instagram_comment(request: Request):
    payload = await request.json()
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change["field"] == "comments":
                data = change["value"]
                post_id = data.get("media", {}).get("id")
                comment_text = data.get("text", "")
                user_id = data.get("from", {}).get("id")
                username = data.get("from", {}).get("name")
                comment_id = data.get("id")

                # Check trigger in our DB
                trigger = await detect_trigger(comment_text, post_id)
                if trigger:
                    video_ctx = await get_video_context(post_id)
                    context = {
                        "platform": "instagram",
                        "username": username,
                        "user_id": user_id,
                        "trigger_phrase": trigger,
                        "post_id": post_id,
                        "comment_id": comment_id,
                        **video_ctx
                    }
                    async with httpx.AsyncClient() as client:
                        await client.post(f"{MAC_AGENT_URL}/agent10/process", json=context)
    return {"status": "ok"}


# ── META WEBHOOK VERIFICATION ────────────────────────────────────────────
@app.get("/webhook/instagram/comments")
async def verify_meta_webhook(hub_mode: str, hub_verify_token: str, hub_challenge: str):
    if hub_mode == "subscribe" and hub_verify_token == os.getenv("META_WEBHOOK_VERIFY_TOKEN"):
        return int(hub_challenge)
    return {"error": "Forbidden"}, 403


async def detect_trigger(comment_text: str, post_id: str):
    result = supabase.table("post_triggers") \
        .select("trigger_phrase") \
        .eq("post_id", post_id) \
        .execute()
    comment_upper = comment_text.upper()
    for row in result.data:
        if row["trigger_phrase"].upper() in comment_upper:
            return row["trigger_phrase"]
    return None


async def get_video_context(post_id: str) -> dict:
    result = supabase.table("post_triggers") \
        .select("*") \
        .eq("post_id", post_id) \
        .maybe_single() \
        .execute()
    return result.data or {}
```

### railway.json (deployment config)

```json
{
  "build": {
    "builder": "NIXPACKS"
  },
  "deploy": {
    "startCommand": "uvicorn railway.webhook_server:app --host 0.0.0.0 --port $PORT",
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

---

## Registering Meta Webhook (one-time setup)

After deploying webhook server, register with Meta:

```bash
curl -X POST "https://graph.facebook.com/v19.0/{app-id}/subscriptions" \
  -d "object=instagram" \
  -d "callback_url=https://kso-webhook-server.up.railway.app/webhook/instagram/comments" \
  -d "fields=comments" \
  -d "verify_token=YOUR_META_WEBHOOK_VERIFY_TOKEN" \
  -d "access_token={app-access-token}"
```

Or via Meta Developer dashboard:
1. Go to developers.facebook.com → Your App → Webhooks
2. Subscribe to Instagram → comments field
3. Callback URL: `https://kso-webhook-server.up.railway.app/webhook/instagram/comments`
4. Verify Token: same as `META_WEBHOOK_VERIFY_TOKEN` in `.env`

---

## Cost Summary

| Railway Service | Monthly Cost |
|---|---|
| Video Builder (on-demand, scales to zero) | ~$15–20 |
| Webhook Server (always-on, tiny) | ~$5 |
| **Total Railway** | **~$20–25/mo** |

---

## Local Safe Mode (no Railway needed for testing)

Set in `.env`:
```bash
VIDEO_RENDER_MODE=local_safe
LOCAL_SAFE_BATCH_SIZE=4
LOCAL_SAFE_PAUSE_SEC=30
```

- Renders 4 videos at a time
- 30-second pause between batches
- All 96 videos take ~2.5 hours total
- Run overnight to avoid any heat
- Use this for Phase 1–3 testing before Railway is set up
