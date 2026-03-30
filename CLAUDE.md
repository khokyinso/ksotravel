# KSO Travel Automation

## Project Overview
Automated travel content pipeline for 12 TikTok/Reels channels.
Generates 96 videos/day across 12 destinations using AI agents.

## Architecture
- **Phase 1**: Trend Scout + Deal Harvester + Content Strategist (Agents 1-3)
- **Phase 2**: Script Writer + Content Auditor (Agents 5-6)
- **Phase 3**: Video Builder + Telegram Gate (Agents 7-8)

## Key Decisions
- TikTok Creative Center is primary trend source (not Google Trends)
- Reddit API blocked, using Playwright scrape as fallback
- Video rendering: LOCAL Mac render (Railway abandoned — too slow, OOM issues)
- Token tracking: per-agent cost monitoring with Telegram alerts
- load_dotenv(override=True) required due to shell env conflicts
- PIL: use Image.LANCZOS not ANTIALIAS (deprecated in Pillow 10+)
- Video compression: bitrate="2000k" to keep files under 50MB (Supabase free limit)
- Pexels footage: use visual_query builder (content_category + destination), NOT raw topic titles
- Footage cache key is brief_id (not destination) — each video gets unique footage

## CRITICAL: Tool/Service Verification Rules
BEFORE recommending any paid service or tool to the user:
1. VERIFY the service has a public API — check developer docs, not just marketing pages
2. CONFIRM the API is included in the subscription plan, not enterprise-only
3. CHECK pricing tiers and what's actually included vs what requires sales contact
4. NEVER recommend signing up for a paid plan without verifying API access first
5. If unsure, tell the user "I need to verify API access before you sign up"

## Verified Free APIs (use these first)
- **Pexels**: Free API, unlimited searches, 200 req/hour — primary footage source
- **Pixabay**: Free API, unlimited searches — fallback footage source
- **TikTok Creative Center**: Free, Playwright scrape (no API key needed)
- **Anthropic**: Paid API (user has key) — all AI generation
- **Supabase**: Free tier — 1GB storage, 50MB upload limit, 2GB bandwidth

## Services That DON'T Have Public APIs (do NOT recommend)
- **Storyblocks**: API is enterprise-only (requires sales contact), NOT included in $21/mo Essentials plan
- **Artgrid**: No public API
- **CapCut**: No public API

## Services Evaluated But Not Used
- **Railway**: Abandoned for video rendering (OOM kills, HTTP timeouts, $20/mo Pro plan wasted)
- **Storyblocks**: User charged $42, API not available on consumer plans — request refund
- **Reddit API**: Account creation blocked by Responsible Builder Policy
- **Google Trends**: Demoted to secondary source (lagging indicator)

## Cost Tracking
- **Kling AI**: ~$0.60-2.10 per 30s video, ~$700-2400/mo at scale — too expensive pre-revenue
- **Supabase free tier**: 50MB upload limit per file, 1GB total storage
- **Anthropic Haiku**: ~$0.003 per brief/script, ~$0.30/day for full pipeline

## Running
```bash
source venv/bin/activate
python -m orchestrator.run_phase1
python -m orchestrator.run_phase2 --date YYYY-MM-DD
python -m orchestrator.run_phase3 --date YYYY-MM-DD --skip-telegram
```

## Config
- API keys go in `.env` (never commit)
- Channel config: `config/channels.json`
- Content rules: `config/content_rules.json`
