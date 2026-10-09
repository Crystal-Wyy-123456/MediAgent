"""红旗症状识别单元测试 —— 口语化表述、否定句、跨轮次组合与样例脚本回归。"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from backend.agents.preconsult.nodes import _recent_patient_text
from backend.agents.preconsult.red_flags import detect_red_flags, needs_llm_double_check
from backend.reference_data import PRECONSULT_SCRIPT

# 必须命中的口语化表述（漏检会直接影响患者安全）
MUST_HIT: list[str] = [
    "胸闷，快要喘不过气",
    "喘不上气，很难受",
    "感觉上不来气",
    "胸口压得慌，喘不过气来",
    "刚才一阵胸痛得厉害，还一直冒冷汗",
    "突然胸口疼，浑身是汗",
    "刚才晕倒了，不省人事",
    "一侧手脚无力，说话不清",
    "突然抽搐，口吐白沫",
    "咯血两次",
    "这两天解黑便",
    "肚子疼得受不了，一直绞痛",
    "胸闷持续不缓解，越来越重",
    "身上起了风团，还喘不过气",
]

# 明确排除的症状不算命中（否则会误报打断问诊）
MUST_NOT_HIT: list[str] = [
    "主要是胸闷，没有胸痛，也没有心慌气短",
    "没有大汗，也没有晕倒",
    "否认咯血、呕血",
    "没有药物过敏",
]


@pytest.mark.parametrize("text", MUST_HIT)
def test_red_flag_should_hit(text: str) -> None:
    assert detect_red_flags(text), f"未识别到红旗症状：{text}"


@pytest.mark.parametrize("text", MUST_NOT_HIT)
def test_negated_symptom_should_not_hit(text: str) -> None:
    assert detect_red_flags(text) == [], f"否定句被误判为红旗症状：{text}"


def test_negation_only_applies_within_clause() -> None:
    """否定词只在同一小句内生效：前面那句的「没」不能把后面的胸痛也否定掉。"""
    assert detect_red_flags("没精神，胸痛得厉害")


def test_chest_tightness_with_dyspnea_is_critical() -> None:
    """用户反馈的原始表述：胸闷 + 快要喘不过气，必须转医生。"""
    labels = [hit["severity"] for hit in detect_red_flags("胸闷，快要喘不过气")]
    assert "critical" in labels


def test_cross_turn_combination_hits() -> None:
    """分两轮说出的症状，合并后同样要能命中。"""
    state = {"messages": [HumanMessage(content="这两天一直高烧")]}
    scan = _recent_patient_text(state, "胳膊上还看到一些出血点")
    names = {hit["name"] for hit in detect_red_flags(scan)}
    assert "high_fever_with_rash" in names
    # 单看每一轮都不构成红旗，只有合起来才成立
    assert not detect_red_flags("这两天一直高烧")
    assert not detect_red_flags("胳膊上还看到一些出血点")


def test_normal_demo_script_never_triggers() -> None:
    """走查一遍标准预问诊脚本：全程不应触发任何红旗告警。"""
    for text in PRECONSULT_SCRIPT["normal"]:
        assert detect_red_flags(text) == [], f"正常问诊被误判：{text}"


def test_red_flag_demo_script_triggers() -> None:
    for text in PRECONSULT_SCRIPT["red_flag"]:
        if detect_red_flags(text):
            return
    pytest.fail("红旗演示脚本未触发任何告警")


def test_needs_double_check_for_vague_warning() -> None:
    """规则未命中但有预警症状时，要交给语义兜底再判一次。"""
    assert needs_llm_double_check("这两天总觉得胸闷", [])
    assert not needs_llm_double_check("我叫张伟，男，58岁。", [])
