# 06 — CTR Optimization
> Agents 13–14 | Affiliate dashboard scraping | 5 optimization outputs daily

---

## Overview

Agents 13 and 14 run every morning before the content pipeline starts.
Agent 13 scrapes all 4 affiliate dashboards for fresh data.
Agent 14 analyzes that data and pushes optimizations to 5 parts of the system.

```
4:00 AM → Agent 13 scrapes dashboards
4:30 AM → Agent 14 analyzes + pushes optimizations
5:00 AM → Rest of pipeline starts (with updated inputs)
```

---

## Agent 13: Affiliate Dashboard Scraper

**File:** `agents/affiliate_scraper.py`
**Runs on:** Mac (Playwright ARM64 native)
**Schedule:** 4:00 AM EST daily
**Output:** `data/affiliate_data_{date}.json`

### Dashboards Scraped

| Platform | URL | Auth Method | Data Available |
|---|---|---|---|
| Klook | partners.klook.com | Session cookie | Clicks, GMV, commission, top products |
| GetYourGuide | partner.getyourguide.com | API token | Clicks, bookings, commission, CTR |
| Viator | viatorforpartners.com | Session cookie | Clicks, bookings, revenue |
| Booking.com | admin.booking.com/affiliate | Session cookie | Clicks, bookings, commission |

### Scraping Strategy

```python
# agents/affiliate_scraper.py

async def scrape_all():
    results = {}

    # Run all 4 in parallel
    klook, gyg, viator, booking = await asyncio.gather(
        scrape_klook(),
        scrape_getyourguide(),
        scrape_viator(),
        scrape_booking()
    )

    results = {
        "klook": klook,
        "getyourguide": gyg,
        "viator": viator,
        "booking": booking,
        "scraped_at": datetime.utcnow().isoformat()
    }

    # Save to file + Supabase
    save_json(results, f"data/affiliate_data_{today()}.json")
    await supabase.table("ctr_log").insert(results).execute()
    return results


async def scrape_klook():
    """Playwright-based scrape of Klook partner dashboard."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Set session cookie from .env
        await page.context.add_cookies([{
            "name": "session",
            "value": os.getenv("KLOOK_DASHBOARD_SESSION"),
            "domain": "partners.klook.com"
        }])

        await page.goto("https://partners.klook.com/analytics/performance")
        await page.wait_for_load_state("networkidle")

        # Extract performance table
        data = await page.evaluate("""
            () => {
                const rows = document.querySelectorAll('.performance-table tbody tr');
                return Array.from(rows).map(row => ({
                    product: row.cells[0]?.innerText,
                    clicks: parseInt(row.cells[1]?.innerText.replace(',', '')),
                    conversions: parseInt(row.cells[2]?.innerText),
                    revenue: parseFloat(row.cells[3]?.innerText.replace('$', ''))
                }));
            }
        """)
        await browser.close()
        return data
```

### Fallback Chain
1. Try Playwright scrape (primary)
2. If blocked → try official affiliate API endpoint
3. If both fail → use yesterday's cached data + send Telegram alert

### Output Schema Per Link
```json
{
  "platform": "klook",
  "product_name": "JR Hokuriku Arch Pass",
  "destination": "japan",
  "category": "transport",
  "url": "https://klook.com/...",
  "clicks_today": 412,
  "clicks_7d": 2847,
  "conversions_7d": 89,
  "ctr_7d": 0.0312,
  "conversion_rate": 0.031,
  "revenue_7d_usd": 340.80,
  "commission_7d_usd": 20.45,
  "rank_in_category": 1
}
```

---

## Agent 14: CTR Optimizer

**File:** `agents/ctr_optimizer.py`
**Model:** Claude Sonnet 4.6
**Runs on:** Mac
**Schedule:** 4:30 AM EST (after Agent 13 completes)
**Output:** Updates config files + sends to downstream agents

### 5 Optimization Outputs

---

### Output 1: Linktree Reordering
**Destination:** All 12 channel Linktree pages (via Linktree API)
**Logic:** Rank links by clicks in last 24 hours. Top performer → position 1.

```python
async def reorder_linktrees(affiliate_data: dict):
    for channel in CHANNELS:
        destination = channel["destination"]

        # Get all affiliate links for this channel
        links = get_channel_links(destination, affiliate_data)

        # Sort by clicks_today descending
        sorted_links = sorted(links, key=lambda x: x["clicks_today"], reverse=True)

        # Update Linktree
        await linktree_client.reorder(
            page_id=channel["linktree_id"],
            link_order=[link["linktree_link_id"] for link in sorted_links]
        )
```

**Linktree structure (always maintained):**
```
Position 1: Top deal by clicks yesterday (auto-rotated)
Position 2: [Platform] 10% OFF — code KSOTRAVEL
Position 3: All [destination] deals
Position 4: More KSO channels
```

---

### Output 2: CTA Template Winner → Agent 5
**Logic:** Track which comment CTA template drives most: comment → DM → affiliate click

```python
# cta_templates.json is updated daily with current winner
{
  "destinations": {
    "japan": {
      "winner_template": "A",
      "winner_text": "Comment {PHRASE} and I'll send you the full guide",
      "conversion_rate": 0.084,
      "tested_at": "2026-03-21",
      "sample_size": 847
    },
    "france": {
      "winner_template": "D",
      "winner_text": "Comment {PHRASE} for my free {destination} guide",
      "conversion_rate": 0.071,
      "tested_at": "2026-03-21",
      "sample_size": 312
    }
  }
}
```

Agent 5 reads `config/cta_templates.json` at startup each day.

**Template options being tested:**
```
A: "Comment [PHRASE] and I'll send you the full guide"
B: "Drop [PHRASE] below for the complete breakdown"
C: "Type [PHRASE] in comments — I'll DM you the link"
D: "Comment [PHRASE] for my free [destination] guide"
```

Minimum 200 data points before declaring a winner per destination.
Runs continuous A/B rotation — splits 25/25/25/25 across templates until sample reached.

---

### Output 3: Deal Priority Adjustment → Agent 2
**Logic:** Re-weight deal scoring formula based on actual category conversion rates.

```python
# performance_weights.json updated daily
{
  "japan": {
    "category_bonuses": {
      "transport": 0.15,    # +15% because transport converts 3x better
      "attraction": 0.08,
      "food_tour": 0.00,    # No bonus — average performance
      "accommodation": -0.05  # Slight penalty — lowest CTR
    }
  },
  "france": {
    "category_bonuses": {
      "accommodation": 0.15,  # Paris hotel content converts very well
      "food_tour": 0.10,
      "transport": 0.00
    }
  }
}
```

Agent 2 reads this file and adds the bonus to deal scores for that destination.

---

### Output 4: Caption Format Testing → Agent 5
**Logic:** Tests which caption ending drives most Linktree clicks.

```python
CAPTION_CTA_VARIANTS = {
    "A": "Link in bio 👇",
    "B": "Book on {platform} — link in bio 👇",
    "C": "Save 10% with code KSOTRAVEL — link in bio 👇",
    "D": "Full guide in link in bio 👇"
}
```

Agent 14 assigns variant per video (rotated) and tracks which version
correlates with highest Linktree CTR per destination.
Winner updated in `config/cta_templates.json` under `caption_cta_winner`.

---

### Output 5: DM Message Structure → Agent 11
**Logic:** Tests DM message format to maximize affiliate clicks.

Variables tested:
- **Format:** Bullet points vs paragraph
- **Lead:** Price-first vs benefit-first
- **Message 2 timing:** 12h vs 24h vs 48h delay

```python
# dm_ab_config.json updated by Agent 14
{
  "active_tests": {
    "format": "bullets",        # bullets | paragraph
    "lead_with": "benefit",     # benefit | price
    "message_2_delay_hours": 24  # 12 | 24 | 48
  },
  "test_results": {
    "bullets_click_rate": 0.38,
    "paragraph_click_rate": 0.31,
    "benefit_lead_click_rate": 0.41,
    "price_lead_click_rate": 0.35
  }
}
```

---

### Daily CTR Report (Telegram 5:00 AM)

```
💰 CTR Report — March 21, 2026

TOP PERFORMERS:
JR Pass (Japan/Klook)    — 412 clicks | $71 commission
Paris hotel (France/Booking) — 287 clicks | $43 commission
Cappadocia balloon (Turkey/GYG) — 203 clicks | $62 commission

PLATFORM BREAKDOWN:
GetYourGuide  38% of revenue ($2,847)
Klook         29% of revenue ($2,170)
Viator        22% of revenue ($1,645)
Booking.com    9% of revenue ($673) ← underperforming
Expedia        2% of revenue ($149)

OPTIMIZATIONS APPLIED TODAY:
→ 12 Linktrees reordered
→ Template A confirmed winner (9/12 destinations)
→ Japan/Korea transport deals: +0.15 score bonus
→ Booking.com France flagged — low CTR → GYG boosted
→ DM bullet format confirmed winner → 38% click rate
→ Caption variant C winning: "Save 10% with code KSOTRAVEL"
```

---

## CTR Log (Supabase)

```sql
CREATE TABLE ctr_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date DATE NOT NULL,
    platform TEXT,
    product_name TEXT,
    destination TEXT,
    category TEXT,
    affiliate_url TEXT,
    clicks_today INTEGER,
    clicks_7d INTEGER,
    conversions_7d INTEGER,
    ctr_7d DECIMAL,
    conversion_rate DECIMAL,
    commission_7d_usd DECIMAL,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_ctr_log_date ON ctr_log(date, destination);
```
