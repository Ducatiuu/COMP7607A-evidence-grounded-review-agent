import csv
from io import StringIO

import pytest

from scripts.build_human_review_packages import _csv, _embedded_json, _start_here, _validate_sheets


def _blank_rows():
    extraction = [dict(record_id=str(i), human_decision="", human_reason="",
                       reviewer="", reviewed_at="") for i in range(13)]
    questions = [dict(question_id=f"P{i:02d}", reviewer_id="", wording_ok="",
                      answerability_ok="", denominator_ok="", reference_ok="",
                      proposed_edit="", notes="") for i in range(120)]
    return extraction, questions


def test_reviewer_packet_refuses_any_prefilled_human_judgment():
    extraction, questions = _blank_rows()
    _validate_sheets(extraction, questions)
    extraction[4]["human_decision"] = "model_error"
    with pytest.raises(ValueError, match="already contains human work"):
        _validate_sheets(extraction, questions)
    extraction[4]["human_decision"] = ""
    questions[80]["reviewer_id"] = "R1"
    with pytest.raises(ValueError, match="already contains human work"):
        _validate_sheets(extraction, questions)


def test_reviewer_packet_refuses_missing_or_duplicate_rows():
    extraction, questions = _blank_rows()
    extraction[12]["record_id"] = extraction[0]["record_id"]
    with pytest.raises(ValueError, match="duplicate extraction"):
        _validate_sheets(extraction, questions)
    extraction[12]["record_id"] = "12"
    with pytest.raises(ValueError, match="expected 13"):
        _validate_sheets(extraction, questions[:-1])


def test_csv_reader_preserves_source_id_whitespace_and_json_cells():
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["record_id", "gold_aspects"])
    writer.writerow(["184 ", '[{"category":"food","sentiment":"negative"}]'])
    fields, rows = _csv(("\ufeff" + stream.getvalue()).encode("utf-8"))
    assert fields == ["record_id", "gold_aspects"]
    assert rows[0]["record_id"] == "184 "
    assert rows[0]["gold_aspects"] == '[{"category":"food","sentiment":"negative"}]'


def test_embedded_source_text_cannot_close_json_script_element():
    embedded = _embedded_json({"review": '</script><script>alert("run")</script>',
                               "text": "A & B\u2028C"})
    assert "</script>" not in embedded
    assert "<script>" not in embedded
    assert "\\u003c/script>" in embedded
    assert "\\u0026" in embedded
    assert "\\u2028" in embedded


def test_reviewer_handoff_contains_full_guide_without_old_identity_steps():
    guide = "# 抽取差异指南\n五种判断的示例\n\n# **HTML 审核操作与提交**\n2. 手动填写审核代号"
    handoff = _start_here(2, guide).decode("utf-8")
    assert "Reviewer 2（R2）" in handoff
    assert "五种判断的示例" in handoff
    assert "手动填写审核代号" not in handoff
    assert "首次完成日期" in handoff
    assert "分母显示 N/A" in handoff


def test_reviewer_handoff_refuses_guide_without_expected_section():
    with pytest.raises(ValueError, match="missing its HTML handoff section"):
        _start_here(1, "# 不完整指南")
