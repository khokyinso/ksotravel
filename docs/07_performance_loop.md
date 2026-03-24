# 07 — Performance Loop
> Agent 15 | Full funnel tracking | Feedback to all upstream agents | Reports

---

## Agent 15: Performance Analyzer

**File:** `agents/performance_loop.py`
**Model:** Claude Haiku 4.5
**Runs on:** Mac
**Schedule:** 11:00 PM EST daily (end of day, full data available)
**Also:** Real-time viral alert monitor runs separately throughout the day

---

## Full Funnel Tracked

```
Video Views
    ↓
Comment Rate (% of viewers who comment)
    ↓
Trigger Comment Rate (% of comments using trigger phrase)
    ↓
DM Delivery Rate (% of triggered DMs successfully delivered)
    ↓
DM Open Rate (% of delivered DMs opened)
    ↓
Affiliate Link Click Rate (% of DM recipients who click)
    ↓
Conversion Rate (% of clicks that result in purchase)
    ↓
Commission Earned ($)
```

---

## Metrics Collected Per Video

| Metric | Source | Frequency | Weight |
|---|---|---|---|
| Views | TikTok/Meta API | Hourly | High |
| Saves | TikTok/Meta API | Daily | Very High |
| Shares | TikTok/Meta API | Daily | High |
| Comments | TikTok/Meta API | Daily | Medium |
| Watch completion % | TikTok/Meta API | Daily | High |
| Trigger comment count | Supabase dm_log | Real-time | Very High |
| DM open rate | Supabase dm_log | Daily | Very High |
| Affiliate link clicks | Linktree analytics | Daily | Critical |
| Affiliate conversions | Platform dashboards | Daily | Critical |
| Commission earned ($) | Klook/GYG/Viator/Booking | Daily | Critical |

---

## Feedback Loops — What Gets Updated

### → Agent 3 (Content Strategist)

```python
# Updates performance_weights.json with:
{
  "destination_weights": {
    "japan": 1.0,     # Baseline
    "korea": 0.95,    # Slightly below Japan
    "france": 1.15,   # Growing fast — increase content
    "poland": 0.75    # Underperforming — reduce until hooks improve
  },
  "hook_angle_weights": {
    "warning": 1.0,   # Top performer — baseline
    "hack": 0.92,
    "comparison": 0.87,
    "story": 0.71,
    "listicle": 0.68
  },
  "optimal_length_by_category": {
    "transport": 30,
    "food_tour": 45,
    "accommodation": 30,
    "attraction": 15,
    "visa_entry": 60
  }
}
```

### → Agent 5 (Script Writer)

```python
# Updates top_hooks.json with this week's best performers
{
  "top_10_hooks_this_week": [
    "Stop wasting money on the JR Pass",
    "Never stay in central Paris — here's why",
    "I saved $90 on Japan rail — here's how",
    "Tourists always make this mistake in Istanbul",
    "Don't buy Colosseum tickets on the day",
    ...
  ],
  "worst_hooks_this_week": [
    "3 things to do in Greece",   # → add to soft blacklist
    "Japan travel tip for you"     # → too vague
  ]
}
```

### → Agent 9 (Publisher)

```python
# Updates posting_times.json with refined slots per channel
{
  "kso.japan": {
    "slot_1": "07:15",  # Was 07:00 — shifted 15 min based on engagement peak
    "slot_6": "19:30",  # Was 19:00 — audience peaks later
    ...
  }
}
```

### → Agent 11 (DM Sender)

```python
# Updates dm_config.json with best-performing message structure
{
  "message_1_format": "bullets",
  "message_1_lead": "benefit",
  "message_2_delay_hours": 24,
  "best_performing_categories_by_channel": {
    "kso.japan": "transport",
    "kso.france": "accommodation",
    "kso.korea": "experience"
  }
}
```

### → Agent 14 (CTR Optimizer)

```python
# Provides full conversion funnel data to cross-reference with CTR data
{
  "video_to_click_correlation": {
    "high_saves_correlate_with_clicks": True,
    "watch_completion_correlation": 0.73,
    "comment_rate_correlation": 0.61
  }
}
```

---

## New Channel Bootstrap Logic

France, Turkey, Poland, China have no performance history at launch.
Agent 15 applies a 30-day bootstrap period:

| Days | Strategy |
|---|---|
| 1–14 | Mirror Japan/Korea hook patterns (proven) |
| 15–28 | A/B test destination-specific angles |
| Day 29+ | Fully data-driven per-channel optimization |

---

## Real-Time Viral Alert Monitor

**File:** `agents/viral_monitor.py`
**Schedule:** Checks every 15 minutes throughout the day (separate from main Agent 15)
**Threshold:** >50,000 views in 6 hours

```python
async def check_viral_alerts():
    recent_videos = await get_videos_last_24h()

    for video in recent_videos:
        age_hours = (now() - video.published_at).total_seconds() / 3600
        if age_hours <= 6 and video.views >= 50000:
            await send_viral_alert(video)


async def send_viral_alert(video):
    channel_emoji = CHANNEL_EMOJIS[video.channel]
    msg = f"""
🚨 VIRAL ALERT — {video.channel.upper()}
"{video.hook_text}"

📈 {format_num(video.views)} views / {video.age_hours:.1f}hrs
💾 {format_num(video.saves)} saves
💬 {format_num(video.trigger_comments)} trigger comments
📩 {format_num(video.dms_sent)} DMs sent
🔗 {format_num(video.affiliate_clicks)} affiliate clicks
💰 ${video.commission_usd:.0f} commission so far

→ POST A FOLLOW-UP VIDEO ON THIS TOPIC TODAY
→ Suggested angle: {await generate_followup_suggestion(video)}
    """
    await telegram_client.send(msg)
```

---

## Weekly Report (Monday 8:00 AM EST)

```
📈 KSO Weekly Report — Week of March 17

━━━━━━━━━━━━━━━━━━━━━
CONTENT PERFORMANCE
━━━━━━━━━━━━━━━━━━━━━
Total views: 6.1M across 12 channels
Top channel: KSO.Japan (1.1M views)
Fastest growing: KSO.France (+380% WoW)
Top video: "Never stay in central Paris" (89K views, 4,100 saves)
Best hook angle: warning (avg 2.3× more saves than listicle)

━━━━━━━━━━━━━━━━━━━━━
FUNNEL PERFORMANCE
━━━━━━━━━━━━━━━━━━━━━
Trigger comments received: 14,832
DMs sent: 13,940 (94% delivery)
DM open rate: 71%
Affiliate clicks from DMs: 3,847
DM→purchase conversion: 4.2%

Instagram DM CTR: 38% (native API — no ManyChat)
TikTok DM CTR: 31% (ManyChat Starter trigger)

━━━━━━━━━━━━━━━━━━━━━
AFFILIATE REVENUE
━━━━━━━━━━━━━━━━━━━━━
GetYourGuide:  $3,240 (best performer)
Klook:         $2,180
Viator:        $1,640
Booking.com:     $320 (underperforming — session cookie limitation)
Expedia:         $149
─────────────────────
Total:         $7,529 this week

━━━━━━━━━━━━━━━━━━━━━
AI OPTIMIZATIONS THIS WEEK
━━━━━━━━━━━━━━━━━━━━━
→ KSO.France content weight +15% (growing fastest)
→ Template A CTA confirmed winner (9/12 destinations)
→ China visa content 3× better CTR than food content
→ Japan posting slot 6 shifted from 19:00 → 19:30
→ Booking.com France deprioritized → GYG boosted
→ Bullet-format DMs confirmed winner → 38% vs 31% click rate
→ 24h Message 2 delay confirmed optimal (vs 12h and 48h)
→ KSO.Poland: switch to budget/value angles — warning hooks underperforming

━━━━━━━━━━━━━━━━━━━━━
90-DAY PROGRESS
━━━━━━━━━━━━━━━━━━━━━
Total followers: 34,210 / 120,000 target (28%)
Monthly revenue run rate: $7,529/week → ~$32,625/mo ✅ ahead of target
Pipeline uptime: 97.3% ✅
```

---

## Supabase — Performance Tables

```sql
-- Published videos
CREATE TABLE published_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brief_id TEXT UNIQUE,
    channel TEXT,
    destination TEXT,
    topic TEXT,
    hook_angle TEXT,
    hook_text TEXT,
    trigger_phrase TEXT,
    content_category TEXT,
    video_length_seconds INTEGER,
    tiktok_post_id TEXT,
    tiktok_url TEXT,
    instagram_post_id TEXT,
    instagram_url TEXT,
    affiliate_url TEXT,
    deal_platform TEXT,
    published_at TIMESTAMP DEFAULT NOW()
);

-- Video performance (updated daily per video)
CREATE TABLE video_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brief_id TEXT REFERENCES published_videos(brief_id),
    platform TEXT,
    views INTEGER DEFAULT 0,
    saves INTEGER DEFAULT 0,
    shares INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    trigger_comments INTEGER DEFAULT 0,
    watch_completion_pct DECIMAL DEFAULT 0,
    affiliate_clicks INTEGER DEFAULT 0,
    conversions INTEGER DEFAULT 0,
    commission_usd DECIMAL DEFAULT 0,
    recorded_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_perf_brief ON video_performance(brief_id, recorded_at);
CREATE INDEX idx_perf_channel ON video_performance(platform, recorded_at);
```
