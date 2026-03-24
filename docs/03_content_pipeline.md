# 03 — Content Pipeline
> Agents 1–9 | Trend → Deals → Briefs → Scripts → Audit → Video → Review → Publish

---

## Pipeline Flow

```
[Agent 1: Trend Scout]    [Agent 2: Deal Harvester]
        ↓                          ↓
        └──── [Agent 3: Content Strategist] ────┘
                         ↓
              [Agent 4: Channel Router]
                         ↓
              [Agent 5: Script Writer]
                         ↓
             [Agent 6: Content Auditor]
                    ↓         ↓         ↓
                  PASS      REVISE     FAIL
                    ↓         ↓         ↓
             Agent 7    Agent 5    Agent 3
                    ↓
          [Agent 7: Video Builder] ← Railway
                    ↓
        [Agent 8: Telegram Review Gate]
                    ↓
        [Agent 9: Scheduler/Publisher]
```

---

## Agent 1: Trend Scout

**File:** `agents/trend_scout.py`
**Model:** Claude Haiku 4.5
**Schedule:** 5:00 AM EST daily
**Output:** `data/trends_{date}.json`

### Job
Identify 12+ trending travel topics per destination (144 signals minimum daily).
Generates enough material for Agent 3 to pick the best 8 per channel.

### Data Sources
- **Google Trends API** — rising/breakout travel queries by country
- **Reddit** — r/JapanTravel, r/solotravel, r/ThailandTourism, r/travel, r/EuropeTravel, r/ItalyTravel, r/greece, r/korea, r/mexicotravel, r/PortugalExpats, r/spain, r/france, r/turkey, r/poland, r/china, r/Chinavisa
- **TikTok hashtags** — Playwright scrape of trending travel hashtags (ARM64 native)
- **Seasonal calendar** — holiday/peak dates all 12 destinations (see below)
- **Agent 15 feedback** — last 7 days top-performing topics per channel

### Seasonal Calendar (built-in logic)

| Destination | Flag Dates |
|---|---|
| Japan | Golden Week Apr 29–May 5, Cherry Blossom Mar–Apr, Obon Aug |
| China | Golden Week Oct 1–7, Chinese New Year (varies), May Day |
| Korea | Chuseok (varies), cherry blossom Apr, monsoon Jul–Aug |
| Thailand | Songkran Apr 13–15, high season Nov–Mar |
| France | Bastille Day Jul 14, August peak, Christmas markets Dec |
| Turkey | Ramadan (varies), summer peak Jul–Aug, tulip season Apr |
| Poland | Christmas markets Dec, summer low crowds |
| Greece | Easter (varies), high season Jul–Aug, shoulder Apr–May + Sep–Oct |

### Hook Angles (ranked by proven performance)
1. `warning` — "avoid this / don't do this / stop making this mistake"
2. `hack` — "save $X by doing this instead"
3. `secret` — "nobody tells you this / locals only know this"
4. `timing` — "only/never go during X"
5. `comparison` — "X vs Y — which is worth it"
6. `listicle` — "3 things you must do in X"
7. `story` — "I spent $X on this so you don't have to"
8. `reaction` — "tourists always do this wrong"

### Output Schema
```json
{
  "date": "2026-03-21",
  "destination": "japan",
  "trends": [
    {
      "topic": "JR Pass price increase 2026",
      "hook_angle": "warning",
      "urgency": "high",
      "search_volume_trend": "rising",
      "content_category": "transport",
      "suggested_hook": "Don't buy a JR Pass before reading this",
      "suggested_length_seconds": 30
    }
  ]
}
```

---

## Agent 2: Deal Harvester

**File:** `agents/deal_harvester.py`
**Model:** Claude Haiku 4.5
**Schedule:** 5:00 AM EST (parallel with Agent 1)
**Output:** `data/deals_{date}.json`

### Job
Score and rank 10+ affiliate deals per destination per day across 5 platforms.

### Scoring Formula
```
deal_score = (commission_rate * 0.4) + (review_score * 0.3)
           + (booking_velocity * 0.2) + (urgency_flag * 0.1)
```
Agent 14 adds +0.15 bonus to categories with historically high CTR per destination.

### Platform Priority by Destination

| Destination | P1 | P2 | P3 |
|---|---|---|---|
| Japan | Klook | Viator | GYG |
| Greece | GYG | Viator | Klook |
| Italy | Viator | GYG | Booking |
| Korea | Klook | GYG | Viator |
| Thailand | GYG | Klook | Viator |
| Mexico | Viator | GYG | Klook |
| Portugal | Booking | GYG | Viator |
| Spain | GYG | Viator | Booking |
| France | GYG | Booking | Viator |
| Turkey | Klook | GYG | Viator |
| Poland | GYG | Booking | Viator |
| China | Viator | Klook | GYG |

### Deal Categories
`transport` | `attraction` | `food_tour` | `accommodation` | `experience` | `day_trip` | `guided_tour`

### Output Schema
```json
{
  "destination": "japan",
  "deals": [
    {
      "platform": "klook",
      "product_name": "JR Hokuriku Arch 7-Day Pass",
      "affiliate_url": "https://klook.com/...",
      "price_usd": 160,
      "commission_pct": 6,
      "deal_score": 0.82,
      "urgency": "limited availability",
      "category": "transport"
    }
  ]
}
```

---

## Agent 3: Content Strategist

**File:** `agents/content_strategist.py`
**Model:** Claude Haiku 4.5
**Schedule:** 5:30 AM EST
**Output:** `data/briefs_{date}.json` (96 briefs)

### Job
Generate 8 content briefs per channel (96 total). AI decides full content mix daily.
Assigns comment trigger phrase to every video.

### Content Mix Logic (fully AI-decided daily)
- Analyses trend signals + available deals + 7-day content history + Agent 15 weights
- Selects 8 highest-potential topic/deal combos per destination
- No fixed template — dynamic based on what's working

### Hard Rules (all channels)
- No duplicate topic within 60 days on same channel
- Max 3 same-category videos per channel per day
- Min 2 `warning` or `hack` hooks per channel per day
- Min 1 affiliate deal per channel per day
- Every video gets a unique trigger phrase
- China: min 1 visa/entry tip per day
- France/Turkey/Poland: min 1 underrated vs overtouristed angle per day

### Video Length Decision (AI per topic)

| Content Type | Length |
|---|---|
| Single tip / warning | 15s |
| Tip + context + deal | 30s |
| Comparison (X vs Y) | 30–45s |
| Listicle / story | 45–60s |

### Trigger Phrase Rules
- 1–3 words max
- Directly related to video topic
- Easy to type in a comment
- Same phrase used on TikTok and Instagram for the same video

### Sample Video Selection
Flags exactly 1 brief per channel as `is_sample_video: true`.
Selection: highest-stakes factual claim (price, visa info, official dates).
This is the video Kelvin reviews in Telegram.

### Brief Output Schema
```json
{
  "brief_id": "france_005_20260321",
  "channel": "kso.france",
  "destination": "france",
  "topic": "Best Paris neighborhoods to stay under $150",
  "hook_angle": "hack",
  "hook_text": "Never stay in central Paris — here's why",
  "content_category": "accommodation",
  "target_length_seconds": 30,
  "is_sample_video": false,
  "deal": {
    "platform": "booking",
    "product": "Montmartre boutique hotel",
    "url": "https://booking.com/...",
    "price_usd": 89,
    "commission_pct": 5,
    "promo_code": "KSOTRAVEL"
  },
  "comment_trigger_phrase": "PARIS STAY",
  "dm_payload_type": "accommodation_guide",
  "posting_slot": 5,
  "posting_time_est": "17:00"
}
```

---

## Agent 4: Channel Router

**File:** `agents/channel_router.py`
**Model:** Claude Haiku 4.5
**Schedule:** 5:45 AM EST
**Output:** adds `posting_time_est` to each brief

### Job
Assign 8 posting slots per channel, minimum 2 hours apart (TikTok hard limit).

### Posting Slots (EST) — Audience-Based
See `docs/01_channels.md` for rationale. All 12 channels target US audience peak times.

| Slot | Time (EST) |
|---|---|
| 1 | 7:00 AM |
| 2 | 9:30 AM |
| 3 | 12:00 PM |
| 4 | 2:30 PM |
| 5 | 5:00 PM |
| 6 | 7:00 PM |
| 7 | 8:30 PM |
| 8 | 10:00 PM |

Agent 15 refines these times per channel after 30 days of real engagement data.
Updated times written to `config/performance_weights.json`.

---

## Agent 5: Script Writer

**File:** `agents/script_writer.py`
**Model:** Claude Sonnet 4.6
**Schedule:** 6:00 AM EST — parallel batches of 12
**Output:** `data/scripts_{date}.json`

### Job
Write 96 scripts in KSO's proven format. Each script includes:
- Comment CTA line with trigger phrase (second-to-last)
- Affiliate CTA with promo code (last line)
- CTA template from Agent 14's current winner

### Script Format by Length

**15s (5 lines):**
```
Line 1: Hook (≤8 words, creates urgency/curiosity)
Line 2: Tip — specific detail
Line 3: Tip — real price or name
Line 4: Comment CTA with trigger phrase
Line 5: Platform name + code KSOTRAVEL
```

**30s (7 lines):**
```
Line 1: Hook
Lines 2–5: Tip + context + deal detail
Line 6: Comment CTA with trigger phrase
Line 7: Platform name + code KSOTRAVEL
```

**45–60s (10 lines):**
```
Line 1: Hook
Lines 2–8: Full tip / list / story
Line 9: Comment CTA with trigger phrase
Line 10: Platform name + code KSOTRAVEL
```

### CTA Templates (A/B tested by Agent 14 — rotate winner)
```
A: "Comment [PHRASE] and I'll send you the full guide"
B: "Drop [PHRASE] below for the complete breakdown"
C: "Type [PHRASE] in comments — I'll DM you the link"
D: "Comment [PHRASE] for my free [destination] guide"
```

### System Prompt Core
```
You write TikTok/Reels scripts for @insearchofkso travel channels.
Voice: confident, specific, direct, urgent. First-person preferred.

RULES:
- Every line ≤ 8 words
- Always include real USD prices
- Always include real product/place names
- Always include promo code KSOTRAVEL
- NEVER start: "If you are traveling to..."
- NEVER use vague language ("some", "many", "often")
- Second-to-last line = comment CTA with provided trigger phrase
- Last line = affiliate platform + KSOTRAVEL

PROVEN HOOK STARTERS:
"Stop wasting money on [X] in [destination]"
"Most tourists make this mistake in [destination]"
"Don't visit [destination] without knowing this"
"I saved $X by doing this instead"
"Never book [X] before checking [Y]"
"[Destination] locals never tell tourists this"

DESTINATION NOTES:
- China: mention visa type / VPN / payment when relevant
- Turkey: USD prices only — never Turkish Lira
- Poland: emphasize budget angle (Europe's best value)
- France: subvert Parisian clichés ("Everyone goes to Paris, go here instead")
```

### Output Schema
```json
{
  "brief_id": "france_005_20260321",
  "script_lines": [
    "Never stay in central Paris — here's why",
    "Montmartre hotel costs $89 per night",
    "1st arrondissement costs $280 for same quality",
    "15-minute metro from all major attractions",
    "Comment PARIS STAY for the neighborhood guide",
    "Book via Booking.com — use code KSOTRAVEL"
  ],
  "caption": "Stop overpaying for Paris hotels! Montmartre gives you the same access for 3x less. Comment PARIS STAY and I'll send you the full guide 👇 #paris #france #paristips #travelfrance",
  "hashtags": ["#paris", "#france", "#paristips", "#travelfrance", "#travelhack"],
  "affiliate_url": "https://booking.com/...",
  "geotag": "Paris, France",
  "target_length_seconds": 30
}
```

---

## Agent 6: Content Auditor

**File:** `agents/content_auditor.py`
**Model:** Claude Sonnet 4.6
**Schedule:** 6:30 AM EST — parallel audits
**Output:** `data/audit_results_{date}.json`

### Job
Quality and accuracy gate. Nothing proceeds to video production without clearing all checks.

### Standard Checklist (all channels)

**Factual accuracy (web search verified):**
- [ ] All prices within 15% of current live prices
- [ ] Affiliate URL resolves and product is available
- [ ] Any dates mentioned correct for current year
- [ ] Transport pass coverage accurate

**Script quality:**
- [ ] Hook on Line 1, ≤8 words
- [ ] Line count matches target length (15s=5, 30s=7, 45–60s=10)
- [ ] No line exceeds 8 words
- [ ] Trigger phrase present on second-to-last line
- [ ] Comment CTA correctly formatted
- [ ] KSOTRAVEL promo code present
- [ ] Affiliate URL valid
- [ ] Caption ≤150 chars before hashtags
- [ ] 4–6 hashtags included
- [ ] No duplicate topic in last 60 days (checked against `logs/published.json`)
- [ ] No blacklisted hook openers

**China-specific extra checks:**
- [ ] Visa information verified against official government source (web search)
- [ ] VPN content framed as tourist practical tip — not political
- [ ] No political commentary
- [ ] WeChat/Alipay foreigner access info current

**Turkey:** All prices in USD confirmed
**Poland:** Auschwitz content tone respectful — no clickbait language

### Verdict Logic
```
PASS   → forward to Agent 7
REVISE → return to Agent 5 with specific correction notes (max 2 loops)
FAIL   → kill brief, notify Agent 3 to regenerate for this slot
```

### Audit Output Schema
```json
{
  "brief_id": "france_005_20260321",
  "verdict": "PASS",
  "checks_passed": 14,
  "checks_failed": 0,
  "revision_notes": null
}
```

---

## Agent 7: Video Builder

**File:** `agents/video_builder.py` (Mac stub) + `railway/video_builder_service.py` (cloud)
**Runs on:** Railway cloud (NOT Mac — thermal throttle risk on fanless Air)
**Schedule:** 7:00 AM EST — all 96 in parallel (~30 min)

### Mac Stub Behavior
```python
def build_videos(approved_scripts):
    if os.getenv('VIDEO_RENDER_MODE') == 'local_safe':
        # Overnight fallback: 4 at a time, 30s cooldown
        return render_local_batched(approved_scripts, batch_size=4)
    else:
        # DEFAULT: submit to Railway
        return submit_to_railway(approved_scripts)
```

### Video Spec
- Resolution: 1080×1920 (9:16 vertical)
- Format: MP4 H.264
- Duration: 15/30/45/60s per brief assignment

### Text Overlay Style (KSO brand)
- Font: Bold white, 2px black drop shadow
- Size: 52px standard, 46px for longer lines
- Position: Centered, 40px side padding
- Animation: Fade in per line, 0.3s stagger

### Comment CTA Visual Treatment
Trigger phrase displayed in destination brand color box.
Example: `💬 Comment "PARIS STAY" for the full guide`

### Destination Brand Colors

| Destination | Color | Hex |
|---|---|---|
| Japan | Red | #E8272A |
| Korea | Teal | #00A693 |
| France | Navy | #002395 |
| Italy | Green | #009246 |
| Greece | Blue | #0D5EAF |
| Turkey | Red | #E30A17 |
| Thailand | Gold | #F5C518 |
| Mexico | Green | #006847 |
| Portugal | Green | #006600 |
| Spain | Red | #AA151B |
| Poland | Red | #DC143C |
| China | Red | #DE2910 |

### Footage Tags by Destination

| Destination | Pexels Search Tags |
|---|---|
| Japan | tokyo street, shibuya crossing, mount fuji, bullet train, kyoto temple |
| Greece | santorini, greek island, athens acropolis, aegean sea, mykonos |
| Italy | rome colosseum, amalfi coast, venice canal, tuscany vineyard |
| Korea | seoul street, korean food, gyeongbokgung, k-beauty, busan |
| Thailand | bangkok temple, thai beach, pad thai, tuk tuk, chiang mai |
| Mexico | cenote, oaxaca food, tulum beach, mexico city zocalo |
| Portugal | lisbon tram, porto ribeira, alentejo, douro valley |
| Spain | barcelona sagrada familia, tapas bar, camino de santiago |
| France | paris eiffel, french food, loire valley, nice beach, paris cafe |
| Turkey | istanbul mosque, cappadocia balloon, grand bazaar, bosphorus |
| Poland | krakow old town, warsaw, auschwitz memorial, tatra mountains |
| China | great wall, beijing forbidden city, shanghai skyline, xi an terracotta |

### Music Mood by Destination

| Destination | Mood | BPM |
|---|---|---|
| Japan | Lo-fi, calm | 70–85 |
| Korea | Modern, upbeat | 100–120 |
| China | Ambient, cinematic | 75–90 |
| Thailand | Tropical, ambient | 75–90 |
| Mexico | Vibrant, rhythmic | 110–130 |
| Greece / Italy / Portugal / Spain | Warm, Mediterranean | 80–100 |
| France | Romantic, café jazz | 85–100 |
| Turkey | Exotic, cinematic | 85–100 |
| Poland | Atmospheric, European | 80–95 |

Music volume: 15%. Source: YouTube Audio Library (royalty-free).
Output: MP4 uploaded to Supabase Storage → URL returned to Mac orchestrator.

---

## Agent 8: Telegram Review Gate

**File:** `agents/telegram_gate.py`
**Schedule:** 7:30 AM EST

### Job
Send 12 sample videos to Kelvin (1 per channel). Approving a sample auto-approves
all 8 videos for that channel.

### Review Logic
```
FOR EACH of 12 channels:
  Send 1 sample (highest-stakes video) to Telegram
  → APPROVED: queue all 8 for that channel
  → REJECTED: regenerate sample + hold all 8
  → No response in 90 min: auto-approve (configurable)
```

### Sample Message Format
```
🇫🇷 KSO.France — Sample (video 5 of 8 today)

Hook: "Never stay in central Paris — here's why"
Trigger: "PARIS STAY"
Deal: Booking.com Montmartre hotel $89 — 5% commission
Audit: ✅ 14/14 checks passed

[▶️ Preview] [✅ Approve Channel] [❌ Reject] [✏️ Edit]
```

### Bulk Actions
```
[✅ Approve All 12 Channels]  [📊 View Full Queue]  [⏸️ Pause Today]
```

### Always-On Alerts (bypass review, immediate Telegram)
- Any audit FAIL
- Any publisher API error
- Any affiliate URL returning 404
- China visa policy change detected
- Viral alert: >50K views in 6 hours

---

## Agent 9: Scheduler & Publisher

**File:** `agents/publisher.py`
**Dependencies:** Buffer Agency API, TikTok Content Posting API, Meta Graph API, ManyChat Starter API

### Per-Video Publishing Flow
1. Upload MP4 → TikTok Content Posting API
2. Set caption + hashtags + geotag
3. Log TikTok post ID + URL → Supabase `published_videos`
4. Register trigger phrase in ManyChat Starter (TikTok only)
5. Wait 2 hours
6. Cross-post → Instagram Reels via Meta Graph API
7. Log Instagram post ID + URL → Supabase
8. Register Meta Webhook subscription for this post's comments (Instagram)
9. Update channel Linktree top link → today's newest deal

### TikTok Compliance
- Hard limit: 8 posts/day/account ← system hits exactly this
- Minimum 2 hours between posts ← Agent 4 enforces this
- Monitor for 429 errors → pause 30 min + retry

### Per-Channel Linktree Structure
```
Link 1: Today's featured deal (auto-updated daily by Agent 14)
Link 2: [Platform] 10% OFF — code KSOTRAVEL
Link 3: All [destination] deals
Link 4: More KSO channels (hub page)
```

### Daily Summary (Telegram 11:30 PM EST)
```
✅ KSO Daily Summary — March 21, 2026

🇯🇵 8/8 ✅  🇬🇷 8/8 ✅  🇮🇹 8/8 ✅  🇰🇷 8/8 ✅
🇹🇭 8/8 ✅  🇲🇽 8/8 ✅  🇵🇹 8/8 ✅  🇪🇸 8/8 ✅
🇫🇷 8/8 ✅  🇹🇷 7/8 ⚠️  🇵🇱 8/8 ✅  🇨🇳 8/8 ✅

Total: 95/96 | TikTok: 95 | Reels: 95
Est. revenue today: $80–320
```

---

## Content Rules — All Channels

**Never post:**
- Prices more than 30 days out of date
- Duplicate topic within 60 days on same channel
- More than 3 same-category videos per channel per day

**Hook blacklist (never use these openers):**
- "If you are traveling to X..."
- "Here are some tips for..."
- "In this video I will show you..."
- "Today I want to talk about..."

See `docs/10_guardrails.md` for full content rules per destination.
