"""规则引擎轨是确定性的 —— 给同样的病历必然得到同样的结论。"""

from __future__ import annotations

from backend.agents.medreview.nodes import compute_weighted_score, grade_of
from backend.agents.medreview.rules import RULES, run_rule_track
from backend.reference_data import SAMPLE_RECORDS
from backend.infra.local_engine.medreview import extract_record


def test_rule_ids_unique():
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))


def test_sample_record_hits_expected_rules():
    record = extract_record({"raw_document": SAMPLE_RECORDS[0]["text"]})
    results = {r["rule_id"]: r for r in run_rule_track(record, SAMPLE_RECORDS[0]["text"])}
    # 该样例故意构造了：入院记录超 24 小时、上级签名缺失、过敏史空缺
    assert results["R001"]["passed"] is False
    assert results["R002"]["passed"] is False
    assert results["R004"]["passed"] is False
    # 首次病程记录在 8 小时内、有主任医师查房
    assert results["R005"]["passed"] is True
    assert results["R007"]["passed"] is True


def test_extraction_reads_all_sections():
    record = extract_record({"raw_document": SAMPLE_RECORDS[0]["text"]})
    assert record["admit_time"] == "2024-03-11 09:20"
    assert record["record_time"] == "2024-03-12 15:40"
    assert "体格检查" in record["sections_found"]
    assert record["physical_exam"].startswith("T 36.8")
    assert record["allergy_history"] == ""
    assert any("冠心病" in d for d in record["diagnosis"])


def test_weighted_score_and_grade():
    rules = [{"passed": True, "weight": 3.0}, {"passed": False, "weight": 1.0}]
    dims = [{"score": 9.0}, {"score": 9.0}]
    score = compute_weighted_score(rules, dims, [])
    assert 7.0 < score <= 10.0
    assert grade_of(9.6).startswith("甲级")
