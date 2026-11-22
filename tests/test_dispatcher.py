from src.tools import dispatch_tool, trace_summary
from test_tools import _dataset


def test_dispatcher_allowlist_and_validation():
    ctx = _dataset()
    good = dispatch_tool(ctx, call_id="1", name="filter_records", arguments={"conditions": [{"category": "food", "sentiment": "positive"}]})
    assert good.status == "ok" and good.data["record_ids"] == ["R01", "R03"]
    unknown = dispatch_tool(ctx, call_id="2", name="run_python", arguments={"code": "print(1)"})
    assert unknown.status == "failed" and unknown.error == "unknown_tool"
    invalid = dispatch_tool(ctx, call_id="3", name="get_evidence", arguments={"record_ids": ["unknown"]})
    assert invalid.status == "failed" and invalid.error == "invalid_tool_arguments_or_scope"


def test_evidence_trace_summary_omits_raw_review_text():
    result = dispatch_tool(_dataset(), call_id="4", name="get_evidence", arguments={"record_ids": ["R01"]})
    summary = trace_summary(result)
    assert summary["all_record_ids"] == ["R01"]
    assert "text" not in str(summary) and "service was slow" not in str(summary)
