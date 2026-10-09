"""Agent 级集成测试：三个 Agent 的真实图都能跑通，且行为符合设计约束。"""

from __future__ import annotations

import uuid

import pytest
from langgraph.types import Command

from backend.agents.medqa.graph import build_medqa_graph
from backend.agents.medreview.graph import build_medreview_graph
from backend.agents.preconsult.graph import build_preconsult_graph, graph_config
from backend.reference_data import SAMPLE_RECORDS


@pytest.mark.asyncio
async def test_medqa_knowledge_path_has_citations():
    graph = build_medqa_graph()
    result = await graph.ainvoke({"query": "二甲双胍的禁忌症有哪些？", "messages": [], "tenant_id": "tnt_renhe"})
    assert result["query_type"] == "KNOWLEDGE"
    assert result["citations"], "医学结论必须带引用来源"
    assert result["fallback_used"] is False


@pytest.mark.asyncio
async def test_medqa_chitchat_skips_retrieval():
    graph = build_medqa_graph()
    result = await graph.ainvoke({"query": "你好", "messages": [], "tenant_id": "tnt_renhe"})
    assert result["query_type"] == "CHITCHAT"
    assert not result.get("retrieved_docs")


@pytest.mark.asyncio
async def test_medqa_refuses_low_confidence():
    graph = build_medqa_graph()
    result = await graph.ainvoke({"query": "今天股市怎么样", "messages": [], "tenant_id": "tnt_renhe"})
    assert result["fallback_used"] is True
    assert "拒答" in result["answer"] or "覆盖不足" in result["answer"]


@pytest.mark.asyncio
async def test_medreview_three_tracks_and_issues():
    graph = build_medreview_graph()
    result = await graph.ainvoke({"raw_document": SAMPLE_RECORDS[0]["text"], "tenant_id": "tnt_renhe"})
    assert len(result["rule_results"]) == 8
    assert len(result["dimension_results"]) == 6  # 六维度并发
    assert result["issues"], "该样例应命中多条质控问题"
    assert 0 <= result["overall_score"] <= 10
    # 每条问题都必须有可审计的证据原文
    assert all(issue.get("evidence") is not None for issue in result["issues"])


@pytest.mark.asyncio
async def test_preconsult_full_flow_reaches_finished():
    graph = build_preconsult_graph()
    sid = f"sess_test_{uuid.uuid4().hex[:6]}"
    pid = "pat_test"
    config = graph_config("tnt_renhe", pid, sid)
    state = {
        "session_id": sid, "tenant_id": "tnt_renhe", "patient_id": pid,
        "current_stage": "WARMUP", "stage_turn_count": 0, "filled_slots": {},
        "slot_values": {}, "followup_count": 0, "rephrase_count": 0, "messages": [], "turn_count": 0,
    }
    result = await graph.ainvoke(state, config)
    assert result.get("current_question")

    answers = [
        "我叫张伟，男，58岁。",
        "最近3天反复胸闷，活动以后更明显。",
        "三天前开始，走路快一点就胸闷，休息几分钟能缓解，没有明显诱因，晚上睡觉时没有发作，还伴有出汗。",
        "主要是胸闷，没有胸痛，也没有心慌气短。",
        "有高血压5年，一直在吃氨氯地平，没有药物过敏。",
        "氨氯地平每天早上一片，规律在吃，没有漏服。",
        "基本准确，另外补充一下我有2型糖尿病。",
    ]
    for answer in answers:
        result = await graph.ainvoke({"patient_message": answer, "messages": []}, config)
    assert result["current_stage"] == "FINISHED"
    assert result["draft_record"]["chief_complaint"].startswith("胸闷")
    assert "__interrupt__" not in result


@pytest.mark.asyncio
async def test_preconsult_red_flag_interrupt_and_resume():
    graph = build_preconsult_graph()
    sid = f"sess_rf_{uuid.uuid4().hex[:6]}"
    config = graph_config("tnt_renhe", "pat_rf", sid)
    state = {
        "session_id": sid, "tenant_id": "tnt_renhe", "patient_id": "pat_rf",
        "current_stage": "WARMUP", "stage_turn_count": 0, "filled_slots": {},
        "slot_values": {}, "followup_count": 0, "rephrase_count": 0, "messages": [], "turn_count": 0,
    }
    await graph.ainvoke(state, config)
    paused = await graph.ainvoke({"patient_message": "突然胸痛得厉害，还一直冒冷汗"}, config)

    # interrupt() 挂起：状态被 Checkpointer 保存，图没有继续往下走
    assert "__interrupt__" in paused
    alert = paused["__interrupt__"][0].value
    assert alert["type"] == "RED_FLAG_ALERT"
    assert alert["options"] == ["take_over", "continue", "refer_emergency"]

    # 医生接管：Command(resume=) 从断点继续，不重跑之前的节点
    resumed = await graph.ainvoke(
        Command(resume={"action": "take_over", "doctor_id": "D00123", "note": "立即心电图"}),
        config,
    )
    assert resumed["handover"] is True
    assert resumed["doctor_id"] == "D00123"
    assert "胸痛" in "".join(resumed["handover_reason"])
