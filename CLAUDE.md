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
- Video rendering: Railway cloud (async submit + poll pattern)
- Token tracking: per-agent cost monitoring with Telegram alerts
- load_dotenv(override=True) required due to shell env conflicts
- moviepy v1 pinned (<2.0.0) on Railway for editor import compat

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
