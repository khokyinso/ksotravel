-- KSO Travel Automation — Supabase Schema
-- Phase 1: Intelligence Layer (Agents 1-3)

-- ============================================================
-- TRENDS: Raw trend signals from Agent 1 (Trend Scout)
-- ============================================================
CREATE TABLE IF NOT EXISTS trends (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    destination TEXT NOT NULL,
    topic TEXT NOT NULL,
    hook_angle TEXT NOT NULL,
    urgency TEXT NOT NULL DEFAULT 'medium',
    search_volume_trend TEXT,
    content_category TEXT NOT NULL,
    suggested_hook TEXT,
    suggested_length_seconds INTEGER DEFAULT 30,
    video_format TEXT DEFAULT 'green_screen_text',
    source TEXT,
    source_signal TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trends_date_dest ON trends (date, destination);
CREATE INDEX idx_trends_destination ON trends (destination);

-- ============================================================
-- DEALS: Scored affiliate deals from Agent 2 (Deal Harvester)
-- ============================================================
CREATE TABLE IF NOT EXISTS deals (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    destination TEXT NOT NULL,
    platform TEXT NOT NULL,
    product_name TEXT NOT NULL,
    affiliate_url TEXT NOT NULL,
    price_usd NUMERIC(10, 2),
    commission_pct NUMERIC(5, 2),
    deal_score NUMERIC(5, 4) NOT NULL DEFAULT 0,
    urgency TEXT,
    category TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_deals_date_dest ON deals (date, destination);
CREATE INDEX idx_deals_score ON deals (deal_score DESC);

-- ============================================================
-- BRIEFS: Content briefs from Agent 3 (Content Strategist)
-- ============================================================
CREATE TABLE IF NOT EXISTS briefs (
    id BIGSERIAL PRIMARY KEY,
    brief_id TEXT UNIQUE NOT NULL,
    date DATE NOT NULL,
    channel TEXT NOT NULL,
    destination TEXT NOT NULL,
    topic TEXT NOT NULL,
    hook_angle TEXT NOT NULL,
    hook_text TEXT NOT NULL,
    content_category TEXT NOT NULL,
    target_length_seconds INTEGER NOT NULL DEFAULT 30,
    is_sample_video BOOLEAN NOT NULL DEFAULT FALSE,
    deal_platform TEXT,
    deal_product TEXT,
    deal_url TEXT,
    deal_price_usd NUMERIC(10, 2),
    deal_commission_pct NUMERIC(5, 2),
    comment_trigger_phrase TEXT NOT NULL,
    dm_payload_type TEXT,
    video_format TEXT DEFAULT 'green_screen_text',
    posting_slot INTEGER,
    posting_time_est TEXT,
    source_signal TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_briefs_date ON briefs (date);
CREATE INDEX idx_briefs_channel ON briefs (channel);
CREATE INDEX idx_briefs_status ON briefs (status);
CREATE INDEX idx_briefs_brief_id ON briefs (brief_id);

-- ============================================================
-- PUBLISHED_VIDEOS: Track what's been published (for dedup)
-- ============================================================
CREATE TABLE IF NOT EXISTS published_videos (
    id BIGSERIAL PRIMARY KEY,
    brief_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    destination TEXT NOT NULL,
    topic TEXT NOT NULL,
    content_category TEXT NOT NULL,
    hook_angle TEXT NOT NULL,
    tiktok_post_id TEXT,
    tiktok_url TEXT,
    instagram_post_id TEXT,
    instagram_url TEXT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_published_channel_topic ON published_videos (channel, topic);
CREATE INDEX idx_published_date ON published_videos (published_at);
CREATE INDEX idx_published_destination ON published_videos (destination);

-- ============================================================
-- PERFORMANCE_WEIGHTS: Feedback from Agent 15 (future phase)
-- ============================================================
CREATE TABLE IF NOT EXISTS performance_weights (
    id BIGSERIAL PRIMARY KEY,
    destination TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    weight NUMERIC(5, 4) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(destination, metric_type, metric_key)
);

-- ============================================================
-- PIPELINE_RUNS: Track each daily pipeline execution
-- ============================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    phase TEXT NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    briefs_generated INTEGER DEFAULT 0,
    errors JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX idx_pipeline_runs_date ON pipeline_runs (date);

-- ============================================================
-- SCRIPTS: Generated scripts from Agent 5 (Script Writer)
-- ============================================================
CREATE TABLE IF NOT EXISTS scripts (
    id BIGSERIAL PRIMARY KEY,
    brief_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    script_json JSONB NOT NULL,
    model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_scripts_brief_id ON scripts (brief_id);

-- ============================================================
-- AUDIT_RESULTS: Audit verdicts from Agent 6 (Content Auditor)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_results (
    id BIGSERIAL PRIMARY KEY,
    brief_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    verdict TEXT NOT NULL,
    issues JSONB DEFAULT '[]'::jsonb,
    revision_notes TEXT,
    model TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_brief_id ON audit_results (brief_id);
CREATE INDEX idx_audit_verdict ON audit_results (verdict);

-- ============================================================
-- API_USAGE_LOGS: Token and cost tracking per API call
-- ============================================================
CREATE TABLE IF NOT EXISTS api_usage_logs (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    agent_name TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd NUMERIC(10, 6) NOT NULL,
    context JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_usage_date ON api_usage_logs (date);
CREATE INDEX idx_usage_agent ON api_usage_logs (agent_name, date);

-- ============================================================
-- PROMPT_OPTIMIZATION: Daily pass rate tracking per agent
-- ============================================================
CREATE TABLE IF NOT EXISTS prompt_optimization (
    id BIGSERIAL PRIMARY KEY,
    date DATE NOT NULL,
    agent_name TEXT NOT NULL,
    model TEXT NOT NULL,
    total_calls INTEGER NOT NULL DEFAULT 0,
    pass_count INTEGER NOT NULL DEFAULT 0,
    revise_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    pass_rate NUMERIC(5, 4) NOT NULL DEFAULT 0,
    avg_cost_per_call NUMERIC(10, 6) DEFAULT 0,
    prompt_version TEXT DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(date, agent_name, model)
);

CREATE INDEX idx_prompt_opt_agent ON prompt_optimization (agent_name, date);

-- ============================================================
-- RENDERED_VIDEOS: Video render results from Agent 7
-- ============================================================
CREATE TABLE IF NOT EXISTS rendered_videos (
    id BIGSERIAL PRIMARY KEY,
    brief_id TEXT UNIQUE NOT NULL,
    date DATE NOT NULL,
    destination TEXT NOT NULL,
    video_url TEXT NOT NULL,
    duration_seconds INTEGER,
    render_status TEXT NOT NULL DEFAULT 'rendered',
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rendered_brief_id ON rendered_videos (brief_id);
CREATE INDEX idx_rendered_date ON rendered_videos (date);
CREATE INDEX idx_rendered_status ON rendered_videos (render_status);

-- Add cost tracking columns to pipeline_runs
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS total_cost_usd NUMERIC(10, 6) DEFAULT 0;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS total_input_tokens INTEGER DEFAULT 0;
ALTER TABLE pipeline_runs ADD COLUMN IF NOT EXISTS total_output_tokens INTEGER DEFAULT 0;

-- ============================================================
-- ROW LEVEL SECURITY (optional, enable if needed)
-- ============================================================
-- ALTER TABLE trends ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE deals ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE briefs ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE published_videos ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE performance_weights ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
