"""数据层 —— 业务数据 + 会话摘要 + Trace 落表。

默认 SQLite（开箱即用，零外部依赖）；配置 DATABASE_URL 为 PostgreSQL 时
换成 asyncpg 驱动即可，SQL 保持同构（DDL 见 deploy/schema.sql）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from ..config import RUNTIME_DIR, settings

_DDL = """
CREATE TABLE IF NOT EXISTS tenant (
    tenant_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    hospital_level TEXT,
    config         TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS session (
    session_id     TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    user_id        TEXT NOT NULL,
    agent_type     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    summary        TEXT,
    state_snapshot TEXT,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_tenant_user ON session(tenant_id, user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS message (
    message_id  TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    citations   TEXT,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_session ON message(session_id, created_at);

CREATE TABLE IF NOT EXISTS record_review (
    review_id         TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL,
    patient_name      TEXT,
    structured_record TEXT NOT NULL,
    dimension_results TEXT NOT NULL,
    rule_results      TEXT NOT NULL,
    cross_doc_results TEXT,
    overall_score     REAL,
    grade             TEXT,
    status            TEXT NOT NULL DEFAULT 'pending',
    elapsed_ms        REAL,
    created_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_tenant_time ON record_review(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS review_issue (
    issue_id    TEXT PRIMARY KEY,
    review_id   TEXT NOT NULL,
    dimension   TEXT NOT NULL,
    severity    TEXT NOT NULL,
    title       TEXT NOT NULL,
    evidence    TEXT NOT NULL,
    location    TEXT,
    suggestion  TEXT,
    source_rule TEXT,
    accepted    INTEGER,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_issue_review ON review_issue(review_id);

CREATE TABLE IF NOT EXISTS preconsult_record (
    record_id   TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    patient_id  TEXT,
    current_stage TEXT NOT NULL,
    filled_slots  TEXT NOT NULL DEFAULT '{}',
    chief_complaint TEXT,
    hpi         TEXT,
    past_history TEXT,
    medication_history TEXT,
    allergy_history TEXT,
    completeness_score REAL,
    handover    INTEGER NOT NULL DEFAULT 0,
    handover_reason TEXT,
    handover_doctor_id TEXT,
    draft_record TEXT,
    summary     TEXT,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_preconsult_tenant ON preconsult_record(tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_trace (
    request_id  TEXT PRIMARY KEY,
    tenant_id   TEXT,
    user_id     TEXT,
    session_id  TEXT,
    agent_type  TEXT,
    route_level TEXT,
    status      TEXT,
    fallback_used INTEGER,
    token_in    INTEGER,
    token_out   INTEGER,
    elapsed_ms  REAL,
    span_count  INTEGER,
    query       TEXT,
    created_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_trace_created ON agent_trace(created_at DESC);
"""


class Database:
    """一个极简异步包装：SQLite 阻塞调用丢到线程池执行，接口与 asyncpg 同构。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()
        self._seed_tenants()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── 同步原语（内部使用）──
    def _execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        assert self._conn is not None
        self._conn.execute(sql, tuple(params))
        self._conn.commit()

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        assert self._conn is not None
        cur = self._conn.execute(sql, tuple(params))
        return [dict(row) for row in cur.fetchall()]

    # ── 异步接口 ──
    async def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        await asyncio.get_running_loop().run_in_executor(None, self._execute, sql, tuple(params))

    async def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return await asyncio.get_running_loop().run_in_executor(None, self._query, sql, tuple(params))

    async def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = await self.fetch_all(sql, params)
        return rows[0] if rows else None

    def _seed_tenants(self) -> None:
        now = time.time()
        tenants = [
            ("tnt_huadong", "华东医科大学附属第一医院", "三级甲等", {"knowledge_scope": "全院"}),
            ("tnt_huaxi", "西南区域医疗中心", "三级甲等", {"knowledge_scope": "全院"}),
            ("tnt_renhe", "仁和医院", "三级甲等", {"knowledge_scope": "院内知识库"}),
        ]
        for tid, name, level, config in tenants:
            self._execute(
                "INSERT OR IGNORE INTO tenant(tenant_id, name, hospital_level, config) VALUES (?,?,?,?)",
                (tid, name, level, json.dumps(config, ensure_ascii=False)),
            )
        del now


def _sqlite_path() -> Path:
    url = settings.database_url
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///") :]
        path = Path(raw)
        return path if path.is_absolute() else (RUNTIME_DIR / path)
    return RUNTIME_DIR / "mediagent.db"


db = Database(_sqlite_path())
