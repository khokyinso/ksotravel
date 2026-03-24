# 08 — Mac Setup Guide
> MacBook Air Apple Silicon (M1/M2/M3/M4) | ARM64 native | No Rosetta needed

---

## Why MacBook Air Works for This System

Most of the system is API calls — lightweight, no heavy compute.
The only CPU-intensive task (video rendering) runs on Railway cloud, not your Mac.

Your Mac handles: orchestration, API calls, scheduling, scraping, Telegram bot.
Railway handles: video rendering (Agent 7) + webhook server (Agents 10, 12).

**Mac CPU load is under 30% for most of the day.**

---

## Prerequisites Check

```bash
# Check your chip
system_profiler SPHardwareDataType | grep "Chip"
# Should show: Apple M1, M2, M3, or M4

# Check macOS version (need Ventura 13+ or Sonoma 14+)
sw_vers -productVersion
```

---

## Step 1: Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After install, follow the "Next steps" shown in terminal. Typically:
```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

Verify:
```bash
brew --version
# Should show: Homebrew 4.x.x
which brew
# Should show: /opt/homebrew/bin/brew  (NOT /usr/local — that's Intel)
```

---

## Step 2: Install System Dependencies

```bash
# Python 3.11 (stable, well-tested on Apple Silicon)
brew install python@3.11

# FFmpeg (video processing — required by moviepy)
brew install ffmpeg

# Node.js (for Claude Code)
brew install node

# Git
brew install git

# Verify
python3.11 --version    # Python 3.11.x
ffmpeg -version         # ffmpeg version 6.x
node --version          # v20.x.x
git --version           # git version 2.x
```

---

## Step 3: Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code

# Verify
claude --version
```

If permission error:
```bash
sudo npm install -g @anthropic-ai/claude-code
```

---

## Step 4: Create Project + Virtual Environment

```bash
# Create project
mkdir kso-travel-automation
cd kso-travel-automation

# Create virtual environment using Python 3.11
python3.11 -m venv venv

# Activate (do this EVERY time you open a new terminal)
source venv/bin/activate

# Your prompt should now show: (venv) your-name@MacBook...
```

**Important:** Always activate venv before running anything:
```bash
source venv/bin/activate
```

Add to your `~/.zshrc` for convenience:
```bash
echo 'alias kso="cd ~/kso-travel-automation && source venv/bin/activate"' >> ~/.zshrc
source ~/.zshrc
# Now type 'kso' to activate project from anywhere
```

---

## Step 5: Install Python Dependencies

```bash
# Make sure venv is active first
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

If any package fails with architecture error:
```bash
arch -arm64 pip install <package-name>
```

---

## Step 6: Install Playwright (for scraping)

```bash
# Install Playwright
pip install playwright

# Install ARM64 Chromium browser
playwright install chromium

# If that fails, try:
PLAYWRIGHT_BROWSERS_PATH=0 playwright install chromium
```

Verify:
```bash
python3 -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
```

---

## Step 7: Configure Environment Variables

```bash
# Copy example file
cp .env.example .env

# Edit with your keys
nano .env
# Or open in VS Code:
code .env
```

### API Keys — Where to Get Each

| Key | Where | Time to get |
|---|---|---|
| `ANTHROPIC_API_KEY` | platform.anthropic.com → API Keys | 2 min |
| `SUPABASE_URL` + `SUPABASE_KEY` | supabase.com → Project Settings → API | 5 min |
| `TELEGRAM_BOT_TOKEN` | Telegram → @BotFather → /newbot | 3 min |
| `TELEGRAM_CHAT_ID` | Send message to bot, then visit api.telegram.org/bot{TOKEN}/getUpdates | 2 min |
| `GOOGLE_TRENDS_API_KEY` | console.cloud.google.com → Enable Trends API | 10 min |
| `REDDIT_CLIENT_ID` | reddit.com/prefs/apps → Create app (script type) | 5 min |
| `PEXELS_API_KEY` | pexels.com/api | 2 min |
| `RAILWAY_API_KEY` | railway.app → Account Settings → Tokens | 2 min |

**Phase 1 only needs:** ANTHROPIC + SUPABASE + TELEGRAM + GOOGLE_TRENDS + REDDIT
Everything else needed in later phases.

---

## Step 8: Set Up Supabase

```bash
# Supabase is free tier to start
# 1. Go to supabase.com → New Project
# 2. Copy URL and anon key to .env
# 3. Run schema:

# In Supabase dashboard → SQL Editor → paste contents of:
# database/supabase_schema.sql
# Click Run
```

---

## Step 9: Launch Claude Code

```bash
cd kso-travel-automation
source venv/bin/activate
claude
```

### Phase 1 Prompt for Claude Code
```
Read CLAUDE.md and docs/03_content_pipeline.md.

Build Phase 1 — Intelligence Layer:
- agents/trend_scout.py (Agent 1)
- agents/deal_harvester.py (Agent 2)
- agents/content_strategist.py (Agent 3)
- utils/supabase_client.py
- utils/duplicate_checker.py
- config/channels.json
- config/seasonal_calendar.json
- config/content_rules.json
- database/supabase_schema.sql
- requirements.txt (Mac ARM64 compatible)

Output: Save 96 content briefs per day to data/briefs_{date}.json
No video production yet — intelligence layer only.
All packages must be Apple Silicon ARM64 native.
```

---

## Verification Checks

Run these after setup to confirm everything works:

```bash
# 1. Confirm Python is ARM64 native (not Rosetta)
python3 -c "import platform; print(platform.machine())"
# Expected: arm64

# 2. Confirm FFmpeg is ARM64
file $(which ffmpeg)
# Expected: ...Mach-O 64-bit executable arm64

# 3. Confirm Playwright works
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://example.com')
    print('Title:', page.title())
    browser.close()
"
# Expected: Title: Example Domain

# 4. Confirm Anthropic API works
python3 -c "
import anthropic, os
from dotenv import load_dotenv
load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
msg = client.messages.create(
    model='claude-haiku-4-5',
    max_tokens=50,
    messages=[{'role': 'user', 'content': 'Say OK'}]
)
print(msg.content[0].text)
"
# Expected: OK

# 5. Confirm Supabase connection
python3 -c "
from supabase import create_client
import os
from dotenv import load_dotenv
load_dotenv()
client = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
print('Supabase connected:', bool(client))
"
# Expected: Supabase connected: True
```

---

## Troubleshooting

### Package install fails with architecture error
```bash
arch -arm64 pip install <package>
```

### FFmpeg not found at runtime
```bash
which ffmpeg
# If empty: brew install ffmpeg
# If found but still failing: add to PATH
export PATH="/opt/homebrew/bin:$PATH"
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zprofile
```

### Playwright Chromium fails to launch
```bash
# Reinstall
playwright install --force chromium
# Or install system deps
brew install --cask chromium
```

### "command not found: claude" after npm install
```bash
npm config set prefix '~/.npm-global'
export PATH="$HOME/.npm-global/bin:$PATH"
echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> ~/.zprofile
npm install -g @anthropic-ai/claude-code
```

### Mac gets warm during scraping
Enable local_safe video mode in `.env`:
```bash
VIDEO_RENDER_MODE=local_safe
```
This is a fallback for when Railway is not set up yet. Renders 4 videos at a time
with 30-second cooldowns. Run it overnight to avoid any heat issues.

### Monitor Mac temperature
```bash
# Install Stats app (menubar CPU/temp monitor)
brew install --cask stats

# Or use terminal:
sudo powermetrics --samplers smc -i1 -n1 | grep -i temp
```

---

## requirements.txt

```txt
# Core
anthropic>=0.25.0
python-dotenv>=1.0.0

# API + Web server
fastapi>=0.110.0
uvicorn>=0.29.0
httpx>=0.27.0
requests>=2.31.0

# Scraping (ARM64 native)
playwright>=1.42.0
beautifulsoup4>=4.12.0

# Data
pandas>=2.2.0
numpy>=1.26.0
pydantic>=2.6.0

# Video (Railway primary, local fallback)
moviepy>=1.0.3
Pillow>=10.2.0

# Database
supabase>=2.4.0

# Scheduling
schedule>=1.2.0
apscheduler>=3.10.0
tenacity>=8.2.0

# Telegram
python-telegram-bot>=21.0

# PDFs (DM guides)
fpdf2>=2.7.0

# Logging
loguru>=0.7.0

# Google
google-api-python-client>=2.120.0

# Reddit
praw>=7.7.0
```

All packages confirmed ARM64 native as of March 2026.
