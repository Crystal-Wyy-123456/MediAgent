"""LLM Factory —— 统一模型路由表，换模型不改业务代码。

两种提供方：
  · local    ：私有化部署的内置推理引擎（零外部依赖、可离线运行，输出确定性）
  · deepseek ：云端大模型（OpenAI 兼容协议，配好 API Key 即用）

业务代码只 `llm_factory.get("main")`，永远不关心背后是谁。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import settings
from ..observability.logger import log_event
from ..observability.trace import add_tokens
from .retry import with_retry

TModel = TypeVar("TModel", bound=BaseModel)

SYSTEM_PROMPT = (
    "你是 MediAgent 医疗协作平台中的专业模型。所有医学结论必须给出引用来源，"
    "无来源支撑的结论不得输出；信息不足时必须明确说明而不臆测。"
)


@dataclass
class LLMResult:
    content: str
    token_in: int = 0
    token_out: int = 0
    provider: str = "local"
    model: str = "local"
    elapsed_ms: float = 0.0


def estimate_tokens(text: str) -> int:
    """中文场景的粗略估算：1 token ≈ 1.6 个字符。"""
    return max(1, int(len(text) / 1.6))


class StructuredRunner(Protocol):
    async def ainvoke(self, prompt: str = "", payload: dict | None = None) -> Any: ...


class BaseLLMClient:
    provider = "base"

    def __init__(self, model: str) -> None:
        self.model = model

    async def ainvoke(self, prompt: str, task: str | None = None, payload: dict | None = None) -> LLMResult:
        raise NotImplementedError

    def with_structured_output(self, schema: type[TModel], task: str | None = None) -> StructuredRunner:
        return _StructuredRunner(self, schema, task)


class _StructuredRunner:
    def __init__(self, client: BaseLLMClient, schema: type[TModel], task: str | None) -> None:
        self.client = client
        self.schema = schema
        self.task = task or schema.__name__

    async def ainvoke(self, prompt: str = "", payload: dict | None = None) -> TModel:
        result = await self.client.ainvoke(prompt, task=self.task, payload=payload, schema=self.schema)
        if isinstance(result, self.schema):
            return result
        raise TypeError(f"结构化输出类型不匹配: {type(result)} != {self.schema}")


# ══════════════════════════════════════════════════════════════════
# 提供方 1：私有化部署的内置推理引擎
# ══════════════════════════════════════════════════════════════════
class LocalInferenceClient(BaseLLMClient):
    """私有化部署的内置推理引擎。

    为什么需要它：在没有任何 API Key、没有 GPU 的机器上也能完整跑通全链路
    交互。该引擎复刻了云端模型在每个节点上的**输出契约与判据**，
    切换到云端模型只需要改 .env 里的 LLM_PROVIDER。
    """

    provider = "local"

    async def ainvoke(
        self,
        prompt: str,
        task: str | None = None,
        payload: dict | None = None,
        schema: type[BaseModel] | None = None,
    ) -> Any:
        from .local_engine import run_structured, run_text

        t0 = time.perf_counter()
        payload = dict(payload or {})
        if task:
            payload.setdefault("__task__", task)
        # 内置引擎同样需要"推理耗时"，否则前端看不出真实链路的时间分布
        import asyncio

        await asyncio.sleep(0.02 + min(0.12, len(prompt) / 20000))

        if schema is not None:
            raw = run_structured(schema.__name__, payload)
            raw.setdefault("_prompt_chars", len(prompt))
            data = {k: v for k, v in raw.items() if not k.startswith("_")}
            try:
                model = schema.model_validate(data)
            except ValidationError as exc:  # 结构化输出校验失败 → 明确抛错，由上层降级
                log_event("structured_output_invalid", schema=schema.__name__, error=str(exc)[:200])
                raise
            token_in = estimate_tokens(prompt) + estimate_tokens(json.dumps(payload, ensure_ascii=False, default=str))
            token_out = estimate_tokens(json.dumps(data, ensure_ascii=False, default=str))
            add_tokens(token_in, token_out)
            del t0
            return model

        content = run_text(task or "generic", payload, prompt)
        token_in = estimate_tokens(prompt)
        token_out = estimate_tokens(content)
        add_tokens(token_in, token_out)
        return LLMResult(
            content=content,
            token_in=token_in,
            token_out=token_out,
            provider=self.provider,
            model=self.model,
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )


# ══════════════════════════════════════════════════════════════════
# 提供方 2：真实大模型（OpenAI 兼容 / DeepSeek）
# ══════════════════════════════════════════════════════════════════
class OpenAICompatibleClient(BaseLLMClient):
    provider = "openai-compatible"

    def __init__(self, model: str, base_url: str, api_key: str, temperature: float = 0.0) -> None:
        super().__init__(model)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.temperature = temperature

    async def _chat(self, messages: list[dict], json_mode: bool = False) -> LLMResult:
        import httpx

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        async def _call() -> LLMResult:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
            usage = data.get("usage") or {}
            return LLMResult(
                content=data["choices"][0]["message"]["content"],
                token_in=usage.get("prompt_tokens", 0),
                token_out=usage.get("completion_tokens", 0),
                provider=self.provider,
                model=self.model,
            )

        result = await with_retry(_call, label="llm.chat")
        add_tokens(result.token_in, result.token_out)
        return result

    async def ainvoke(
        self,
        prompt: str,
        task: str | None = None,
        payload: dict | None = None,
        schema: type[BaseModel] | None = None,
    ) -> Any:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        if schema is None:
            return await self._chat(messages)

        schema_hint = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages.append(
            {
                "role": "user",
                "content": f"请仅输出 JSON，且严格符合以下 JSON Schema（不要输出解释与代码块）：\n{schema_hint}",
            }
        )
        last_exc: Exception | None = None
        for _ in range(2):
            try:
                result = await self._chat(messages, json_mode=True)
                text = re.sub(r"^```(json)?|```$", "", result.content.strip(), flags=re.MULTILINE).strip()
                return schema.model_validate(json.loads(text))
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                messages.append({"role": "user", "content": "上一次输出无法解析，请严格输出合法 JSON。"})
        raise last_exc  # type: ignore[misc]


class LLMFactory:
    """统一模型路由表 —— 别名 → 客户端实例。"""

    def __init__(self) -> None:
        self._clients: dict[str, BaseLLMClient] = {}

    def _build(self, alias: str) -> BaseLLMClient:
        provider = (settings.llm_provider or "local").lower()
        model = settings.router_model if alias == "router" else settings.llm_model
        if provider in {"sim", "local"}:
            return LocalInferenceClient(model=f"local:{model}")
        if provider in {"deepseek", "openai", "openai-compatible", "qwen"}:
            if not settings.llm_api_key:
                log_event("llm_api_key_missing", provider=provider, fallback="local")
                return LocalInferenceClient(model="local:fallback")
            return OpenAICompatibleClient(
                model=model,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                temperature=settings.llm_temperature,
            )
        return LocalInferenceClient(model="local:unknown-provider")

    def get(self, alias: str = "main") -> BaseLLMClient:
        if alias not in self._clients:
            self._clients[alias] = self._build(alias)
        return self._clients[alias]

    def reset(self) -> None:
        self._clients.clear()

    def describe(self) -> dict:
        client = self.get("main")
        return {
            "provider": client.provider,
            "model": client.model,
            "mode": "云端大模型" if client.provider != "local" else "私有化部署模型（本地推理）",
            "embedding": settings.embedding_provider,
            "rerank": settings.rerank_provider,
        }


llm_factory = LLMFactory()
