"""Formal runner contract checks. All sources and model replies are synthetic."""

import csv
import json
from pathlib import Path

import pytest

from scripts.plan_formal_experiment import build_plan
from scripts.run_formal_experiment import FormalInputs, checked_plan, main, run_formal
from src.llm_client import LLMResponse
from tests.test_plan_formal_experiment import _arguments, _sha, synthetic_sources


@pytest.fixture
def frozen_case(synthetic_sources, tmp_path):
    args = _arguments(synthetic_sources, tmp_path)
    filled = []
    for slot in (1, 2):
        with args[f"reviewer_{slot}_path"].open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            row.update(reviewer_id=f"R{slot}", wording_ok="yes", answerability_ok="yes",
                       denominator_ok="yes", reference_ok="yes")
        path = tmp_path / f"reviewed_{slot}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        filled.append(path)
    adjudication = tmp_path / "adjudication.json"
    adjudication.write_text(json.dumps({"status": "HUMAN_ADJUDICATED",
                                        "adjudicator_id": "R3", "resolved_question_ids": []}),
                            encoding="utf-8")
    lock = json.loads(args["lock_path"].read_text(encoding="utf-8"))
    release = tmp_path / "release.json"
    release.write_text(json.dumps({
        "status": "FROZEN", "signed_off_by": "fixture-only",
        "pack_ids": lock["pack_ids"], "question_ids": lock["question_ids"],
        "source_sha256": lock["source_sha256"],
        "review_sheet_sha256": {"R1": _sha(filled[0]), "R2": _sha(filled[1])},
        "adjudication_sha256": _sha(adjudication),
        "scoring_rule_version": lock["scoring_rule_version"]}), encoding="utf-8")
    args.update(reviewer_1_path=filled[0], reviewer_2_path=filled[1],
                adjudication_path=adjudication, release_path=release)
    plan = build_plan(**args)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    inputs = FormalInputs(**{
        key: args[key] for key in FormalInputs.__dataclass_fields__})
    return plan_path, inputs, args, plan


class RuleClient:
    def __init__(self, *, fail_on_call=None, input_tokens=10):
        self.requests = []
        self.fail_on_call = fail_on_call
        self.input_tokens = input_tokens

    def complete_json(self, request):
        self.requests.append(request)
        if len(self.requests) == self.fail_on_call:
            raise TimeoutError("secret provider detail must not enter logs")
        if request.stage == "extract":
            content = {"record_id": request.payload["record_id"], "status": "ok",
                       "error": None, "aspects": []}
        elif request.stage == "direct_answer":
            content = {"status": "ok", "answer_text": "No matching reviews."}
        elif request.stage == "query_parse":
            content = {"task_type": "count", "categories": ["service"],
                       "metric": "negative_count"}
        elif request.stage == "dynamic_decision":
            content = {"action": "finish", "calls": []}
        elif request.stage in {"answer", "answer_repair"}:
            content = {"status": "ok", "answer_text": "No matching reviews.",
                       "numeric_claims": request.payload.get("supported_numeric_claims", []),
                       "comparison_groups": request.payload.get("supported_comparison_groups", [])}
        else:
            raise AssertionError(request.stage)
        return LLMResponse(content=content, model="deepseek-flash",
                           input_tokens=self.input_tokens, output_tokens=5)


def _rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_candidate_unreviewed_and_boolean_tampering_cannot_enable_calls(synthetic_sources, tmp_path):
    args = _arguments(synthetic_sources, tmp_path)
    candidate = build_plan(**args)
    plan_path = tmp_path / "candidate.json"
    candidate["execution_permitted"] = True
    candidate["formal_runner_implemented"] = True
    plan_path.write_text(json.dumps(candidate), encoding="utf-8")
    inputs = FormalInputs(**{key: args.get(key) for key in FormalInputs.__dataclass_fields__})
    client = RuleClient()
    with pytest.raises(ValueError, match="differs"):
        run_formal(plan_path, inputs, client=client, authorized=True)
    assert not client.requests and not args["run_dir"].exists()
    candidate = build_plan(**args)
    plan_path.write_text(json.dumps(candidate), encoding="utf-8")
    with pytest.raises(ValueError, match="human review"):
        run_formal(plan_path, inputs, client=client, authorized=True)
    assert not client.requests


def test_frozen_preflight_requires_authorization_and_rechecks_hashes(frozen_case, tmp_path):
    plan_path, inputs, args, plan = frozen_case
    client = RuleClient()
    with pytest.raises(ValueError, match="authorization"):
        run_formal(plan_path, inputs, client=client)
    assert not args["run_dir"].exists() and not client.requests
    assert checked_plan(plan_path, inputs)["plan_sha256"] == plan["plan_sha256"]
    assert main(["--plan", str(plan_path), "--lock", str(inputs.lock_path),
                 "--split", str(inputs.split_path), "--test-csv", str(inputs.test_csv),
                 "--dev-csv", str(inputs.dev_csv), "--questions", str(inputs.questions_path),
                 "--references", str(inputs.references_path), "--test-gold", str(inputs.test_gold_path),
                 "--metrics-code", str(inputs.metrics_path),
                 "--reviewer-1", str(inputs.reviewer_1_path),
                 "--reviewer-2", str(inputs.reviewer_2_path),
                 "--adjudication", str(inputs.adjudication_path),
                 "--release", str(inputs.release_path), "--execute"]) == 2
    assert not args["run_dir"].exists()
    changed = tmp_path / "different.csv"
    changed.write_bytes(inputs.test_csv.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        checked_plan(plan_path, FormalInputs(**{**vars(inputs), "test_csv": changed}))
    malformed = json.loads(plan_path.read_text(encoding="utf-8"))
    malformed["question_ids"][1] = malformed["question_ids"][0]
    plan_path.write_text(json.dumps(malformed), encoding="utf-8")
    with pytest.raises(ValueError, match="differs"):
        checked_plan(plan_path, inputs)


def test_full_synthetic_batch_order_shared_extraction_and_resume(frozen_case):
    plan_path, inputs, args, plan = frozen_case
    first = RuleClient()
    paused = run_formal(plan_path, inputs, client=first, authorized=True, max_tasks=4)
    assert paused["status"] == "PAUSED"
    assert paused["completed_tasks"] == 4 and paused["completed_method_answers"] == 3
    assert [r.stage for r in first.requests[:30]] == ["extract"] * 30
    stages = [r.stage for r in first.requests[30:]]
    assert stages[0] == "direct_answer"
    assert stages.count("query_parse") == 2
    assert stages.count("dynamic_decision") >= 1
    early = _rows(args["run_dir"] / "results.jsonl")
    assert [r["method"] for r in early] == ["a", "b", "c"]
    assert early[0]["shared_extraction_sha256"] is None
    assert early[1]["shared_extraction_sha256"] == early[2]["shared_extraction_sha256"]
    second = RuleClient()
    done = run_formal(plan_path, inputs, client=second, authorized=True, resume=True)
    assert done["status"] == "COMPLETE" and done["completed_method_answers"] == 72
    assert done["completed_tasks"] == 76 and done["formal_score_computed"] is False
    assert sum(done["recorded_answer_status_counts"].values()) == 72
    rows = _rows(args["run_dir"] / "results.jsonl")
    assert len(rows) == 72 and len({r["task_id"] for r in rows}) == 72
    assert {r["pack_id"] for r in rows} == {"P01", "P06", "P11", "P16"}
    assert {r["question_id"] for r in rows} == set(plan["question_ids"])
    for pack in plan["pack_ids"]:
        hashes = {r["shared_extraction_sha256"] for r in rows
                  if r["pack_id"] == pack and r["method"] != "a"}
        assert len(hashes) == 1
    calls = _rows(args["run_dir"] / "calls.jsonl")
    assert len(calls) == done["recorded_requests"] * 2
    assert all(r["input_tokens"] == 10 and r["output_tokens"] == 5
               for r in calls if r["event"] == "end")
    assert all("gold" not in json.dumps(r["request"], ensure_ascii=False).lower()
               and "reference" not in json.dumps(r["request"], ensure_ascii=False).lower()
               for r in calls if r["event"] == "begin")
    assert len(second.requests) < len(calls) // 2
    with pytest.raises(ValueError, match="authorization"):
        run_formal(plan_path, inputs, client=RuleClient(), resume=True)


def test_transport_error_and_budget_limit_preserve_partial_and_block_resume(frozen_case):
    plan_path, inputs, args, _ = frozen_case
    client = RuleClient(fail_on_call=1)
    failed = run_formal(plan_path, inputs, client=client, authorized=True)
    assert failed["status"] == "PARTIAL" and failed["budget_frozen"]
    assert len(client.requests) == 1
    assert "secret provider detail" not in (args["run_dir"] / "calls.jsonl").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="failed, duplicated|uncertain"):
        run_formal(plan_path, inputs, client=RuleClient(), authorized=True, resume=True)


def test_method_transport_failure_is_retained_without_replaying_request(frozen_case):
    plan_path, inputs, args, _ = frozen_case
    client = RuleClient(fail_on_call=31)
    partial = run_formal(plan_path, inputs, client=client, authorized=True)
    assert partial["status"] == "PARTIAL" and partial["recorded_requests"] == 31
    assert sum(partial["recorded_answer_status_counts"].values()) == 1
    rows = _rows(args["run_dir"] / "results.jsonl")
    assert len(rows) == 1 and rows[0]["question_id"] == "P01-Q1"
    assert rows[0]["status"] in {"failed", "execution_error"}
    with pytest.raises(ValueError, match="uncertain|failed, duplicated"):
        run_formal(plan_path, inputs, client=RuleClient(), authorized=True, resume=True)
    assert len(client.requests) == 31


def test_excess_token_usage_closes_budget_before_next_transport(frozen_case):
    plan_path, inputs, args, _ = frozen_case
    client = RuleClient(input_tokens=8193)
    partial = run_formal(plan_path, inputs, client=client, authorized=True)
    assert partial["status"] == "PARTIAL" and partial["budget_frozen"]
    assert partial["recorded_requests"] == 1 and len(client.requests) == 1
    calls = _rows(args["run_dir"] / "calls.jsonl")
    assert calls[1]["input_tokens"] == 8193
    with pytest.raises(ValueError, match="failed, duplicated|usage"):
        run_formal(plan_path, inputs, client=RuleClient(), authorized=True, resume=True)


def test_unknown_call_and_modified_artifact_block_resume(frozen_case):
    plan_path, inputs, args, _ = frozen_case
    run_formal(plan_path, inputs, client=RuleClient(), authorized=True, max_tasks=1)
    extraction = args["run_dir"] / "extractions" / "P01.json"
    extraction.write_bytes(extraction.read_bytes() + b" ")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        run_formal(plan_path, inputs, client=RuleClient(), authorized=True, resume=True)
    extraction.write_bytes(extraction.read_bytes()[:-1])
    with (args["run_dir"] / "calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"event": "begin", "call_id": 31}) + "\n")
    with pytest.raises(ValueError, match="unmatched API request"):
        run_formal(plan_path, inputs, client=RuleClient(), authorized=True, resume=True)
