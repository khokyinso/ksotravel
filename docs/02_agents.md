# 02 — Agents Overview
> 15 agents across 5 layers | Model assignments | Schedules | Where each runs

---

## Agent Map

| # | Agent | Layer | Model | Runs On | Schedule |
|---|---|---|---|---|---|
| 1 | Trend Scout | Content | Haiku 4.5 | Mac | 5:00 AM daily |
| 2 | Deal Harvester | Content | Haiku 4.5 | Mac | 5:00 AM daily (parallel) |
| 3 | Content Strategist | Content | Haiku 4.5 | Mac | 5:30 AM daily |
| 4 | Channel Router | Content | Haiku 4.5 | Mac | 5:45 AM daily |
| 5 | Script Writer | Content | Sonnet 4.6 | Mac | 6:00 AM daily |
| 6 | Content Auditor | Content | Sonnet 4.6 | Mac | 6:30 AM daily |
| 7 | Video Builder | Content | No LLM | **Railway** | 7:00 AM daily |
| 8 | Telegram Review Gate | Content | No LLM | Mac | 7:30 AM daily |
| 9 | Scheduler/Publisher | Content | No LLM | Mac | 8:00 AM+ (throughout day) |
| 10 | Comment Trigger Monitor | DM Engine | Haiku 4.5 | Railway webhook | Real-time |
| 11 | DM Funnel Sender | DM Engine | Sonnet 4.6 | Mac | Triggered by Agent 10 |
| 12 | Comment Reply Bot | Comment AI | Haiku 4.5 | Mac | Every 5 min |
| 13 | Affiliate Scraper | CTR | No LLM | Mac | 4:00 AM daily |
| 14 | CTR Optimizer | CTR | Sonnet 4.6 | Mac | 4:30 AM daily |
| 15 | Performance Analyzer | Loop | Haiku 4.5 | Mac | 11:00 PM daily |

---

## Model Selection Rationale

**Claude Haiku 4.5 ($1/$5 per MTok)** — used for:
- High-volume, structured tasks (trend classification, deal scoring, routing)
- Simple pattern matching (spam detection, trigger phrase detection)
- Performance analysis (summarizing metrics, generating recommendations)
- Cost: ~$22/month for all Haiku agents combined

**Claude Sonnet 4.6 ($3/$15 per MTok)** — used for:
- Quality-critical creative output (scripts, DM messages)
- Nuanced fact-checking and accuracy verification (audit)
- CTR analysis requiring strategic reasoning
- Cost: ~$83/month for all Sonnet agents combined

**No LLM** — used for:
- Video rendering (pure Python/moviepy)
- Publishing (pure API calls)
- Telegram gate (pure bot messaging)
- Affiliate scraping (pure Playwright)

**Total monthly API cost (unoptimized): ~$105**
**With Batch API (50% off) + Prompt Caching (90% off cached): ~$45–55**

---

## Layer 1: Content Production (Agents 1–9)
Full spec in `docs/03_content_pipeline.md`

```
Agent 1 (Trend Scout)
  └─ 12+ trending topics per destination per day
  └─ feeds Agent 3

Agent 2 (Deal Harvester)
  └─ 10+ scored affiliate deals per destination per day
  └─ feeds Agent 3

Agent 3 (Content Strategist)
  └─ 96 content briefs (8 per channel)
  └─ assigns trigger phrase per video
  └─ feeds Agents 4, 5

Agent 4 (Channel Router)
  └─ assigns 8 posting slots per channel per day
  └─ US audience-based timing (see docs/01_channels.md)

Agent 5 (Script Writer)
  └─ 96 scripts in parallel batches of 12
  └─ uses CTA template winner from Agent 14

Agent 6 (Content Auditor)
  └─ 96 audits in parallel
  └─ PASS → Agent 7 | REVISE → Agent 5 | FAIL → regenerate

Agent 7 (Video Builder) ← Railway cloud
  └─ 96 MP4s rendered in parallel (~30 min)
  └─ uploaded to Supabase Storage, URLs returned to Mac

Agent 8 (Telegram Review Gate)
  └─ 12 sample videos sent to Kelvin (1 per channel)
  └─ approve sample = auto-approve all 8 for that channel
  └─ 90-min timeout then auto-approve

Agent 9 (Scheduler/Publisher)
  └─ publishes 8 TikToks + 8 Reels per channel throughout day
  └─ registers ManyChat keyword (TikTok)
  └─ registers Meta Webhook subscription (Instagram)
  └─ updates Linktree per channel
```

---

## Layer 2: DM Engine (Agents 10–11)
Full spec in `docs/04_dm_engine.md`

```
Agent 10 (Comment Trigger Monitor) ← Railway webhook server
  └─ TikTok path: ManyChat Starter webhook → Agent 10
  └─ Instagram path: Meta Webhook → Agent 10 directly (no ManyChat)
  └─ spam/bot filter
  └─ posts public comment reply
  └─ triggers Agent 11

Agent 11 (DM Funnel Sender)
  └─ AI decides DM content based on video context
  └─ sends via TikTok Business API or Meta Graph API
  └─ schedules Message 2 (24h later) in Supabase
  └─ handles opt-outs (STOP keyword)
```

---

## Layer 3: Comment Reply AI (Agent 12)
Full spec in `docs/05_comment_bot.md`

```
Agent 12 (Comment Reply Bot)
  └─ polls all 192 posts every 5 min for new non-trigger comments
  └─ destination Q&A only — hard scope lock
  └─ off-topic → redirect to DM
  └─ prompt injection guard active
  └─ max 3 replies/video/hour, 3 replies/user/day
```

---

## Layer 4: CTR Optimization (Agents 13–14)
Full spec in `docs/06_ctr_optimization.md`

```
Agent 13 (Affiliate Scraper)
  └─ scrapes Klook, GYG, Viator, Booking.com dashboards
  └─ extracts clicks, CTR, conversions, commission per link
  └─ runs 4:00 AM before rest of pipeline

Agent 14 (CTR Optimizer)
  └─ reorders 12 Linktrees daily
  └─ feeds CTA template winner to Agent 5
  └─ adjusts deal scoring for Agent 2
  └─ optimizes DM structure for Agent 11
```

---

## Layer 5: Performance Loop (Agent 15)
Full spec in `docs/07_performance_loop.md`

```
Agent 15 (Performance Analyzer)
  └─ runs 11:00 PM after full day of data
  └─ tracks full funnel: views → comments → DMs → clicks → revenue
  └─ feeds learnings back to Agents 3, 5, 9, 11, 14
  └─ viral alerts (real-time during day via separate monitor)
  └─ weekly report every Monday 8:00 AM
```

---

## Agent Communication Flow

```
Agent 13 ──────────────────────────────────────────────────────┐
Agent 14 ──────────────────┐     ┌─────────────────────────────┤
Agent 15 ──────────────────┤     │   feeds back to              │
                           ↓     ↓                              │
Agent 1 → Agent 3 → Agent 4 → Agent 5 → Agent 6 → Agent 7     │
Agent 2 → Agent 3                           ↓                  │
                                       Agent 8                  │
                                           ↓                    │
                                       Agent 9 ─────────────────┘
                                           ↓
                              [TikTok posts + Instagram Reels live]
                                           ↓
                              Agent 10 (triggered by comments)
                                           ↓
                              Agent 11 (DMs sent)
                                           ↓
                              Agent 12 (comment replies — parallel)
```

---

## Daily Compute Budget (Mac)

Mac is **idle most of the day** — it's waiting on API responses, not doing heavy compute.

| Time | Activity | Mac CPU load |
|---|---|---|
| 4:00–5:00 AM | Affiliate scraping | Low (Playwright + API) |
| 5:00–6:30 AM | Agents 1–5 | Low (API calls) |
| 6:30–7:00 AM | Agent 6 audit (parallel) | Low-Medium |
| 7:00–7:30 AM | **Railway renders videos** | **Mac idle** |
| 7:30–8:00 AM | Telegram gate | Low |
| 8:00 AM–11 PM | Publisher + webhooks | Very low |
| 11:00 PM | Agent 15 analysis | Low |

**Mac never sustains heavy CPU load.** Railway handles the only intensive task.
