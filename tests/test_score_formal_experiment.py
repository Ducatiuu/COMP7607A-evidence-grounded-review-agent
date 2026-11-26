"""Synthetic-only scoring, release and journal reconciliation checks."""

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from eval.questions import GoldReference, QuestionCandidate
from scripts.plan_formal_experiment import build_plan
from scripts.run_formal_experiment import FormalInputs, run_formal
from scripts.score_formal_experiment import (_outcome, _score_question, _sha, score_formal_run,
                                             write_report)
from src.schemas import AnswerPayload, Record, RecordSet
from tests.test_plan_formal_experiment import _arguments, synthetic_sources
from tests.test_run_formal_experiment import RuleClient, frozen_case


@pytest.fixture
def approved_fixture(frozen_case, tmp_path):
    plan_path, inputs, args, _ = frozen_case
    refs = json.loads(inputs.references_path.read_text(encoding="utf-8"))
    final = tmp_path / "human_confirmed_synthetic.json"
    final.write_text(json.dumps([r for r in refs if r["question_id"].startswith(
        ("P01-", "P06-", "P11-", "P16-"))]), encoding="utf-8")
    release = json.loads(inputs.release_path.read_text(encoding="utf-8"))
    release.update(scoring_reference_status="HUMAN_CONFIRMED",
                   scoring_reference_sha256=_sha(final),
                   scoring_reference_question_ids=release["question_ids"])
    inputs.release_path.write_text(json.dumps(release), encoding="utf-8")
    plan = build_plan(**args)
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path, inputs, args, final


def _score(case):
    plan_path, inputs, args, final = case
    return score_formal_run(plan_path=plan_path, inputs=inputs,
                            run_dir=args["run_dir"], final_references_path=final)


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _write_rows(path, rows):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


def test_six_locked_task_semantics_and_price_rate_category():
    records = RecordSet(records=[Record(record_id="R1", text="Service was poor; price was high.")])
    def question(task, **extra):
        return QuestionCandidate(question_id="Q", pack_id="P01", record_ids=["R1"],
                                 task_type=task, wording="synthetic", expected_fields=["value"], **extra)
    cases = [
        ("count", GoldReference(question_id="Q", task_type="count", count=1),
         {"status": "ok", "numeric_claims": [{"metric": "negative_count", "category": "service", "value": 1}]}, {}),
        ("rate", GoldReference(question_id="Q", task_type="rate", numerator=1, denominator=2, rate=0.5),
         {"status": "ok", "numeric_claims": [{"metric": "negative_rate", "category": "price",
                                                "value": 0.5, "numerator": 1, "denominator": 2}],
          "denominator_explanation": "One of two price mentions."},
         {"denominator_spec": "aspect_mentions", "rate_category": "price"}),
        ("selection", GoldReference(question_id="Q", task_type="selection", selected_record_ids=["R1"]),
         {"status": "ok", "selected_record_ids": ["R1"]}, {}),
        ("comparison", GoldReference(question_id="Q", task_type="comparison",
                                     comparison_groups=[["service", "price"]],
                                     category_counts={"service": 1, "price": 1}),
         {"status": "ok", "comparison_groups": [["service", "price"]],
          "numeric_claims": [{"metric": "negative_count", "category": c, "value": 1}
                             for c in ("service", "price")]}, {}),
        ("evidence_explanation", GoldReference(question_id="Q", task_type="evidence_explanation",
                                               comparison_groups=[["service"]],
                                               category_counts={"service": 1}, source_record_ids=["R1"]),
         {"status": "ok", "comparison_groups": [["service"]],
          "numeric_claims": [{"metric": "negative_count", "category": "service", "value": 1}],
          "citations": [{"record_id": "R1", "quote": "Service was poor"}]}, {}),
        ("insufficient_info", GoldReference(question_id="Q", task_type="insufficient_info",
                                             insufficient_info=True),
         {"status": "insufficient_info"}, {"metadata_required": "date"}),
    ]
    for task, reference, payload, extra in cases:
        answer = AnswerPayload(method="a", question_id="Q", answer_text="synthetic", **payload)
        q = question(task, **extra)
        assert _score_question(answer, reference, q, records, rubric="strict")["primary_success"], task
        if task == "rate":
            answer.numeric_claims[0].category = "service"
        elif task == "insufficient_info":
            answer = AnswerPayload(method="a", question_id="Q", status="failed",
                                   answer_text="synthetic", error_code="synthetic_failure")
        elif task == "evidence_explanation":
            answer.citations[0].quote = "invented"
        elif task == "selection":
            answer.selected_record_ids = []
        elif task == "comparison":
            answer.comparison_groups = [["service"], ["price"]]
        else:
            answer.numeric_claims[0].value = 0
        assert not _score_question(answer, reference, q, records, rubric="strict")["primary_success"], task

    price_question = question("rate", denominator_spec="aspect_mentions", rate_category="price")
    price_ref = GoldReference(question_id="Q", task_type="rate", numerator=1,
                              denominator=2, rate=0.5)
    alias = AnswerPayload(method="a", question_id="Q", status="ok", answer_text="half",
                          numeric_claims=[{"metric": "fraction negative among price reviews",
                                           "category": "price", "value": 0.5,
                                           "numerator": 1, "denominator": 2}],
                          denominator_explanation="One of two price mentions")
    assert not _score_question(alias, price_ref, price_question, records,
                               rubric="strict")["primary_success"]
    assert _score_question(alias, price_ref, price_question, records,
                           rubric="bounded_aliases_v1")["primary_success"]


def test_outcomes_distinguish_failure_refusal_and_wrong_answer():
    normal = QuestionCandidate(question_id="Q", pack_id="P01", record_ids=["R1"],
                               task_type="count", wording="x", expected_fields=["count"])
    missing_info = normal.model_copy(update={"task_type": "insufficient_info"})
    assert _outcome(None, normal, None) == "missing"
    assert _outcome({"status": "execution_error"}, normal, None) == "run_error"
    assert _outcome({"status": "failed"}, normal, None) == "model_failure"
    assert _outcome({"status": "partial"}, normal, None) == "partial"
    assert _outcome({"status": "insufficient_info"}, normal, None) == "false_refusal"
    assert _outcome({"status": "insufficient_info"}, missing_info, None) == "valid_refusal"
    assert _outcome({"status": "ok"}, normal, {"primary_success": False}) == "incorrect"


def test_offline_full_report_reconciles_72_answers_and_shared_cost(approved_fixture, tmp_path, monkeypatch):
    plan_path, inputs, args, _ = approved_fixture
    run_formal(plan_path, inputs, client=RuleClient(), authorized=True)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("scorer attempted network")))
    report = _score(approved_fixture)
    assert report["status"] == "SYNTHETIC_DIAGNOSTIC" and not report["formal_score"]
    assert len(report["per_answer"]) == 72 and len(report["paired_questions"]) == 24
    assert all(group["denominator"] == 24 for group in report["methods"].values())
    assert all(group["denominator"] == 4 for method in report["methods"].values()
               for group in method["by_task_type"].values())
    calls = report["calls"]
    assert calls["by_group"]["shared_extraction"]["requests"] == 120
    assert calls["overall"]["requests"] == sum(x["requests"] for x in calls["by_group"].values())
    assert calls["overall"]["input_tokens"] == 10 * calls["overall"]["requests"]
    assert calls["overall"]["output_tokens"] == 5 * calls["overall"]["requests"]
    assert calls["overall"]["latency_ms"] is not None
    assert not calls["anomalies"] and calls["shared_extraction_counted_once"]
    output = tmp_path / "report"
    write_report(report, output)
    assert {p.name for p in output.iterdir()} == {
        "summary.json", "summary.md", "per_answer.csv", "paired_questions.csv"}
    with (output / "paired_questions.csv").open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 24


def test_missing_results_keep_24_denominator_and_refusal_is_distinct(approved_fixture):
    plan_path, inputs, args, _ = approved_fixture
    run_formal(plan_path, inputs, client=RuleClient(), authorized=True, max_tasks=4)
    report = _score(approved_fixture)
    assert report["run_status"] == "PAUSED"
    assert Counter(x["outcome"] for x in report["per_answer"])["missing"] == 69
    assert all(group["denominator"] == 24 for group in report["methods"].values())
    assert report["methods"]["a"]["by_task_type"]["count"]["denominator"] == 4


def test_unfrozen_and_reference_hash_mismatch_are_refused(synthetic_sources, tmp_path, approved_fixture):
    plan_path, inputs, args, final = approved_fixture
    with pytest.raises(ValueError, match="human-confirmed"):
        bad = final.with_name("changed.json")
        bad.write_bytes(final.read_bytes() + b" ")
        score_formal_run(plan_path=plan_path, inputs=inputs, run_dir=args["run_dir"],
                         final_references_path=bad)
    candidate_args = _arguments(synthetic_sources, tmp_path / "candidate")
    candidate = build_plan(**candidate_args)
    path = tmp_path / "candidate_plan.json"
    path.write_text(json.dumps(candidate), encoding="utf-8")
    candidate_inputs = FormalInputs(**{key: candidate_args.get(key)
                                      for key in FormalInputs.__dataclass_fields__})
    with pytest.raises(ValueError, match="human review"):
        score_formal_run(plan_path=path, inputs=candidate_inputs,
                         run_dir=candidate_args["run_dir"], final_references_path=final)


def test_human_signed_but_internally_inconsistent_reference_is_refused(approved_fixture):
    plan_path, inputs, args, final = approved_fixture
    refs = json.loads(final.read_text(encoding="utf-8"))
    rate = next(ref for ref in refs if ref["task_type"] == "rate" and ref["denominator"] > 0)
    rate["denominator"] = 0
    final.write_text(json.dumps(refs), encoding="utf-8")
    release = json.loads(inputs.release_path.read_text(encoding="utf-8"))
    release["scoring_reference_sha256"] = _sha(final)
    inputs.release_path.write_text(json.dumps(release), encoding="utf-8")
    plan_path.write_text(json.dumps(build_plan(**args)), encoding="utf-8")
    with pytest.raises(ValueError, match="final rate reference"):
        _score(approved_fixture)


def test_duplicate_wrong_pack_and_answer_log_mismatch_are_refused(approved_fixture):
    plan_path, inputs, args, _ = approved_fixture
    run_formal(plan_path, inputs, client=RuleClient(), authorized=True, max_tasks=4)
    results = args["run_dir"] / "results.jsonl"
    original = results.read_bytes()
    rows = _rows(results)
    _write_rows(results, [rows[0], rows[0], rows[2]])
    with pytest.raises(ValueError, match="duplicated"):
        _score(approved_fixture)
    rows[0]["pack_id"] = "P06"
    _write_rows(results, rows)
    with pytest.raises(ValueError, match="source or hash"):
        _score(approved_fixture)
    results.write_bytes(original)
    calls = args["run_dir"] / "calls.jsonl"
    events = _rows(calls)
    events[1]["response_sha256"] = "0" * 64
    _write_rows(calls, events)
    with pytest.raises(ValueError, match="response model or hash"):
        _score(approved_fixture)


def test_run_manifest_config_hash_mismatch_is_refused(approved_fixture):
    plan_path, inputs, args, _ = approved_fixture
    run_formal(plan_path, inputs, client=RuleClient(), authorized=True, max_tasks=1)
    path = args["run_dir"] / "run_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["plan"]["source_sha256"]["test_csv"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest or summary"):
        _score(approved_fixture)


def test_failed_request_and_unknown_cost_remain_null(approved_fixture):
    plan_path, inputs, args, _ = approved_fixture
    run_formal(plan_path, inputs, client=RuleClient(fail_on_call=31), authorized=True)
    report = _score(approved_fixture)
    assert report["run_status"] == "PARTIAL" and report["calls"]["overall"]["requests"] == 31
    assert report["calls"]["overall"]["input_tokens"] is None
    assert report["calls"]["overall"]["estimated_cost_usd"] is None
    assert "transport_error" in report["calls"]["anomalies"]
    assert report["outcome_counts"].get("model_failure", 0) + report["outcome_counts"].get("run_error", 0) >= 1
    assert report["outcome_counts"]["missing"] >= 70
