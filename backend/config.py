"""全局配置 —— 所有可调参数集中在这里，通过环境变量或 .env 覆盖。

设计要点：换模型 / 换向量库 / 换数据库都不改业务代码，只改这一层。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_DIR = BASE_DIR / "runtime"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 应用 ──
    app_name: str = "MediAgent"
    app_version: str = "1.0.0"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000

    # ── 认证 ──
    jwt_secret: str = "mediagent-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # ── 模型（LLM Factory 统一路由）──
    # local = 私有化部署的内置推理引擎（零依赖、可离线运行）；deepseek / openai = 云端大模型
    llm_provider: str = "local"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_temperature: float = 0.0
    llm_timeout_s: float = 30.0

    # 路由用的小模型（可以比主模型更便宜）
    router_model: str = "deepseek-chat"

    # ── 检索 ──
    embedding_provider: str = "local"  # local | bge
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 512
    rerank_provider: str = "local"  # local | bge
    rerank_model: str = "BAAI/bge-reranker-large"
    retrieval_top_n: int = 20
    retrieval_top_k: int = 5
    dense_weight: float = 0.7
    sparse_weight: float = 0.3

    # ── 置信度门控（医疗场景：宁可拒答，不可幻觉）──
    confidence_generate: float = 0.62
    confidence_refuse: float = 0.42
    min_docs: int = 2

    # ── 工具层（MCP）──
    mcp_transport: str = "inproc"  # inproc | stdio
    tool_timeout_s: float = 8.0
    tool_max_retries: int = 2

    # ── 数据层 ──
    database_url: str = f"sqlite:///{(RUNTIME_DIR / 'mediagent.db').as_posix()}"
    milvus_uri: str = ""  # 留空表示使用内置轻量向量索引
    milvus_collection: str = "medical_kb"

    # ── 记忆与上下文 ──
    compress_threshold: int = 20
    keep_recent: int = 6
    max_followup: int = 2
    # 预问诊阶段最小轮数放宽为 1，把推进权交给槽位完整性判定
    preconsult_relaxed_turns: bool = True

    # ── 可观测 ──
    trace_success_sample_rate: float = 1.0  # 全量保留便于排障，生产建议 0.05
    trace_max_in_memory: int = 500

    # ── 降级 ──
    retry_max: int = 2
    retry_base_delay: float = 0.3


@lru_cache
def get_settings() -> Settings:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return Settings()


settings = get_settings()
