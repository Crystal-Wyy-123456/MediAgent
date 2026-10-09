-- ════════════════════════════════════════════════════════════════
-- MediAgent PostgreSQL 建表脚本（生产）
-- 本地默认使用 SQLite，表结构与本文件同构（见 backend/infra/db.py）
-- ════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 租户（院区）
CREATE TABLE IF NOT EXISTS tenant (
    tenant_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           VARCHAR(200) NOT NULL,
    hospital_level VARCHAR(50),
    config         JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 会话
CREATE TABLE IF NOT EXISTS session (
    session_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenant(tenant_id),
    user_id        UUID NOT NULL,
    agent_type     VARCHAR(32) NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'active',
    state_snapshot JSONB,
    summary        TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_session_tenant_user ON session(tenant_id, user_id, created_at DESC);

-- 消息
CREATE TABLE IF NOT EXISTS message (
    message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
    role       VARCHAR(16) NOT NULL,
    content    TEXT NOT NULL,
    citations  JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_message_session ON message(session_id, created_at);

-- 病历质控结果
CREATE TABLE IF NOT EXISTS record_review (
    review_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID NOT NULL,
    structured_record JSONB NOT NULL,
    dimension_results JSONB NOT NULL,
    rule_results      JSONB NOT NULL,
    cross_doc_results JSONB,
    overall_score     NUMERIC(5,2),
    grade             VARCHAR(32),
    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
    elapsed_ms        NUMERIC(10,2),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- ★ GIN 索引让 JSONB 内部字段可查（如「查出所有诊断为糖尿病的质控记录」）
CREATE INDEX IF NOT EXISTS idx_review_record_gin ON record_review USING GIN (structured_record jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_review_tenant_time ON record_review(tenant_id, created_at DESC);

-- 质控问题明细（可逐条采纳/驳回）
CREATE TABLE IF NOT EXISTS review_issue (
    issue_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id   UUID NOT NULL REFERENCES record_review(review_id) ON DELETE CASCADE,
    dimension   VARCHAR(32) NOT NULL,
    severity    VARCHAR(10) NOT NULL,
    title       VARCHAR(300) NOT NULL,
    evidence    TEXT NOT NULL,
    location    VARCHAR(200),
    suggestion  TEXT,
    source_rule VARCHAR(32),
    accepted    BOOLEAN,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issue_review ON review_issue(review_id);

-- 预问诊记录
CREATE TABLE IF NOT EXISTS preconsult_record (
    record_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID NOT NULL,
    current_stage      VARCHAR(32) NOT NULL,
    filled_slots       JSONB NOT NULL DEFAULT '{}',
    chief_complaint    TEXT,
    history_of_present_illness TEXT,
    past_history       TEXT,
    medication_history TEXT,
    allergy_history    TEXT,
    completeness_score NUMERIC(5,2),
    handover           BOOLEAN NOT NULL DEFAULT false,
    handover_reason    JSONB,
    handover_doctor_id VARCHAR(64),
    draft_record       JSONB,
    summary            TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_preconsult_tenant ON preconsult_record(tenant_id, created_at DESC);

-- 全链路 Trace（按天落表；失败样本 100% 保留，成功样本按采样率）
CREATE TABLE IF NOT EXISTS agent_trace (
    request_id    VARCHAR(40) PRIMARY KEY,
    tenant_id     VARCHAR(64),
    user_id       VARCHAR(64),
    session_id    VARCHAR(64),
    agent_type    VARCHAR(32),
    route_level   VARCHAR(16),
    status        VARCHAR(16),
    fallback_used BOOLEAN,
    token_in      INTEGER,
    token_out     INTEGER,
    elapsed_ms    NUMERIC(10,2),
    span_count    INTEGER,
    query         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trace_created ON agent_trace(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trace_tenant ON agent_trace(tenant_id, created_at DESC);
