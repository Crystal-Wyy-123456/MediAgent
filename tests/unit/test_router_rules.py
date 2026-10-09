"""L1 规则拦截：命中即零 Token 返回，不进入 LLM 路由。"""

from __future__ import annotations

import pytest

from backend.orchestrator.router import IntentRouter, SessionRegistry
from backend.orchestrator.schema import AgentType


@pytest.fixture()
def router() -> IntentRouter:
    return IntentRouter(SessionRegistry())


def test_social_words_hit_l1(router: IntentRouter):
    result = router._rule_prefilter("你好", "s1")
    assert result is not None
    assert result.level == "L1" and result.reply_type == "social"
    assert result.agent_type is None  # 寒暄不落到任何 Agent


def test_handover_command_hits_l1(router: IntentRouter):
    result = router._rule_prefilter("转人工，我要找医生", "s1")
    assert result is not None and result.reply_type == "handover"


def test_session_inheritance(router: IntentRouter):
    router.sessions.activate("s1", AgentType.MEDREVIEW)
    result = router._rule_prefilter("这里还有问题", "s1")
    assert result is not None
    assert result.agent_type is AgentType.MEDREVIEW
    assert result.reply_type == "continue"


def test_new_task_not_inherited(router: IntentRouter):
    router.sessions.activate("s1", AgentType.MEDREVIEW)
    assert router._rule_prefilter("换个问题：二甲双胍禁忌", "s1") is None


def test_knowledge_query_not_hit(router: IntentRouter):
    assert router._rule_prefilter("二甲双胍的禁忌症有哪些？", "s1") is None


@pytest.mark.asyncio
async def test_llm_route_picks_expected_agent(router: IntentRouter):
    result = await router.route("帮我审一下这份病历的质控问题", "s2")
    assert result.agent_type is AgentType.MEDREVIEW
    result = await router.route("我想挂号，最近胸闷3天", "s3")
    assert result.agent_type is AgentType.PRECONSULT
    result = await router.route("高血压的诊断标准是什么？", "s4")
    assert result.agent_type is AgentType.MEDQA
