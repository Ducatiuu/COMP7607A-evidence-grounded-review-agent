"""Offline, hash-bound scoring of a completed Train-derived development Pilot.

Only candidate Gold is read here. This module must never be imported by a runtime
method or send data to a model provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from eval.metrics import absa_scores, score_answer, summarize_question_scores
from eval.questions import GoldReference, QuestionCandidate
from src.data_loader import load_csv
from src.schemas import AnswerPayload, ExtractionDataset
from src.semeval import GoldRecord


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_hash(path: Path, expected: str) -> None:
    if _sha256(path) != expected:
        raise ValueError(f"source hash mismatch: {path.name}")


def _checked_ledger(path: Path, expected_calls: int) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) != 2 * expected_calls:
        raise ValueError("call ledger length does not match summary")
    totals = {"input_tokens": 0, "output_tokens": 0}
    context_counts: Counter[tuple[str, str | None]] = Counter()
    for index in range(expected_calls):
        begin = json.loads(lines[2 * index])
        end = json.loads(lines[2 * index + 1])
        if (begin.get("event") != "begin" or end.get("event") != "end"
                or begin.get("call_id") != index + 1
                or not isinstance(begin.get("stage"), str)
                or not isinstance(begin.get("method"), str)
                or any(begin.get(key) != end.get(key)
                       for key in ("call_id", "stage", "method", "question_id"))
                or end.get("outcome") != "response"):
            raise ValueError("call ledger has unmatched, failed or reordered calls")
        for key in totals:
            value = end.get(key)
            if type(value) is not int or value < 0:
                raise ValueError("call ledger has invalid token usage")
            totals[key] += value
        context_counts[(begin["method"], begin.get("question_id"))] += 1
    return {**totals, "context_counts": context_counts}


def score_pilot(*, plan_path: Path, run_dir: Path, manifest_path: Path,
                csv_path: Path, questions_path: Path, references_path: Path,
                dev_gold_path: Path) -> dict:
    plan = _json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("invalid plan")
    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":"))
    if (hashlib.sha256(canonical.encode("utf-8")).hexdigest() != plan.get("plan_sha256")
            or Path(plan["planned_run_directory"]).resolve() != run_dir.resolve()
            or plan.get("data_scope") != "TRAIN_DERIVED_DEV_ONLY"
            or plan.get("candidate_review_complete") is not False):
        raise ValueError("plan identity or scope mismatch")
    for path, key in ((manifest_path, "pilot_manifest_sha256"),
                      (csv_path, "pilot_csv_sha256"),
                      (questions_path, "questions_sha256"),
                      (references_path, "references_sha256")):
        _require_hash(path, plan[key])
    manifest = _json(manifest_path)
    if (not isinstance(manifest, dict)
            or manifest.get("status") != "DEV_PILOT_CANDIDATE_UNREVIEWED"
            or manifest.get("human_review_complete") is not False):
        raise ValueError("development candidate review state changed")
    _require_hash(dev_gold_path, manifest["dev_gold_sha256"])

    summary = _json(run_dir / "summary.json")
    marker = _json(run_dir / "run_manifest.json")
    if (not isinstance(summary, dict) or not isinstance(marker, dict)
            or summary.get("status") != "COMPLETE"
            or summary.get("execution_checks_pass") is not True
            or summary.get("pilot_scored_against_references") is not False
            or summary.get("plan_sha256") != plan["plan_sha256"]
            or marker.get("plan_sha256") != plan["plan_sha256"]
            or marker.get("data_scope") != "TRAIN_DERIVED_DEV_ONLY"):
        raise ValueError("run is incomplete or does not match the plan")
    calls = summary.get("actual_requests")
    if (type(calls) is not int or calls < 0
            or summary.get("recorded_transport_calls") != calls):
        raise ValueError("run call count mismatch")
    ledger_totals = _checked_ledger(run_dir / "calls.jsonl", calls)
    if any(summary.get(key) != ledger_totals[key] for key in ("input_tokens", "output_tokens")):
        raise ValueError("run token totals do not match call ledger")

    records = load_csv(csv_path).records
    record_ids = [item.record_id for item in records]
    questions = [QuestionCandidate.model_validate(item) for item in _json(questions_path)]
    references = [GoldReference.model_validate(item) for item in _json(references_path)]
    question_ids = [item.question_id for item in questions]
    if (record_ids != manifest.get("record_ids")
            or question_ids != manifest.get("question_ids")
            or len(record_ids) != plan.get("record_count")
            or len(question_ids) != plan.get("question_count")
            or len(set(question_ids)) != len(question_ids)
            or any(item.record_ids != record_ids or item.status != "CANDIDATE_UNREVIEWED"
                   for item in questions)
            or [item.question_id for item in references] != question_ids
            or any(ref.task_type != question.task_type or ref.status != "CANDIDATE_UNREVIEWED"
                   for ref, question in zip(references, questions))):
        raise ValueError("pilot records, questions or references do not align")
    gold_all = [GoldRecord.model_validate(item) for item in _json(dev_gold_path)]
    gold_by_id = {item.record_id: item for item in gold_all}
    if len(gold_by_id) != len(gold_all) or not set(record_ids).issubset(gold_by_id):
        raise ValueError("development Gold IDs do not align")
    extraction = ExtractionDataset.model_validate(_json(run_dir / "extractions.json"))
    if extraction.records != records:
        raise ValueError("extraction records do not match the Pilot CSV")
    extraction_scores = absa_scores(extraction, [gold_by_id[item] for item in record_ids])

    rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    expected = [(question_id, method) for question_id in question_ids for method in ("a", "b", "c")]
    if (len(rows) != len(expected)
            or len(rows) != summary.get("completed_method_questions")
            or len(rows) != summary.get("planned_method_questions")
            or [(row.get("question_id"), row.get("method")) for row in rows] != expected):
        raise ValueError("result rows are missing, duplicated or reordered")
    ref_by_id = {item.question_id: item for item in references}
    scores_by_method: dict[str, list[dict]] = {method: [] for method in ("a", "b", "c")}
    alias_scores_by_method: dict[str, list[dict]] = {method: [] for method in ("a", "b", "c")}
    noncanonical_metric_rows: dict[str, list[str]] = {method: [] for method in ("a", "b", "c")}
    request_sum = 0
    for row in rows:
        request_count = row.get("requests")
        if type(request_count) is not int or request_count < 0 or "execution_error" in row:
            raise ValueError("result row has invalid request count or execution error")
        request_sum += request_count
        answer = AnswerPayload.model_validate(row["answer"])
        if (answer.method != row["method"] or answer.question_id != row["question_id"]
                or answer.usage.get("api_requests") != request_count):
            raise ValueError("answer identity or request count mismatch")
        task_type = ref_by_id[row["question_id"]].task_type
        expected_metric = {"count": "negative_count", "rate": "negative_rate"}.get(task_type)
        if (answer.status == "ok" and expected_metric
                and not any(claim.metric == expected_metric and claim.category is not None
                            and claim.category.value == "service" for claim in answer.numeric_claims)
                and answer.numeric_claims):
            noncanonical_metric_rows[row["method"]].append(row["question_id"])
        scores_by_method[row["method"]].append(score_answer(answer, ref_by_id[row["question_id"]], records))
        alias_scores_by_method[row["method"]].append(score_answer(
            answer, ref_by_id[row["question_id"]], records,
            metric_rubric="bounded_aliases_v1"))
    if calls - request_sum not in {plan["record_count"], 2 * plan["record_count"]}:
        raise ValueError("shared extraction request count is implausible")
    expected_contexts = Counter({("shared_extraction", None): calls - request_sum})
    expected_contexts.update({(row["method"], row["question_id"]): row["requests"] for row in rows})
    if ledger_totals["context_counts"] != expected_contexts:
        raise ValueError("call ledger method/question counts do not match result rows")
    if dict(Counter(row["answer"]["status"] for row in rows)) != summary.get("answer_status_counts"):
        raise ValueError("answer status summary does not match result rows")

    return {
        "status": "EXPLORATORY_DEV_SCORE",
        "reference_review_complete": False,
        "human_evidence_review_complete": False,
        "formal_test_scored": False,
        "scoring_basis": "strict structured fields against unreviewed candidate references; exact quote and source ID checks do not establish semantic relevance",
        "additional_metric_rubric": "bounded_aliases_v1: clear negative count/rate paraphrases with matching category; rejects ambiguous duplicates",
        "scoring_limitations": ["A free-form metric names can fail the strict structured scorer even when a numeric value matches; inspect flagged rows manually before comparing methods",
                                "candidate references and evidence relevance require independent human review"],
        "plan_sha256": plan["plan_sha256"],
        "source_sha256": {"plan": _sha256(plan_path), "manifest": _sha256(manifest_path),
                          "csv": _sha256(csv_path), "questions": _sha256(questions_path),
                          "references": _sha256(references_path), "dev_gold": _sha256(dev_gold_path),
                          "summary": _sha256(run_dir / "summary.json"),
                          "results": _sha256(run_dir / "results.jsonl"),
                          "calls": _sha256(run_dir / "calls.jsonl"),
                          "extractions": _sha256(run_dir / "extractions.json")},
        "execution_checks_pass": True,
        "actual_requests": calls,
        "extraction": extraction_scores,
        "methods": {method: {"summary": summarize_question_scores(scores),
                             "noncanonical_metric_rows": noncanonical_metric_rows[method],
                             "question_scores": scores}
                    for method, scores in scores_by_method.items()},
        "methods_bounded_aliases_v1": {
            method: {"summary": summarize_question_scores(scores), "question_scores": scores}
            for method, scores in alias_scores_by_method.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a completed dev Pilot locally; no model calls")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--manifest", default="data/processed/dev_pilot/manifest.json")
    parser.add_argument("--csv", default="data/processed/dev_pilot/pilot.csv")
    parser.add_argument("--questions", default="data/processed/dev_pilot/questions.json")
    parser.add_argument("--references", default="data/gold/dev_pilot/references.json")
    parser.add_argument("--dev-gold", default="data/gold/dev.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    report = score_pilot(plan_path=Path(args.plan), run_dir=Path(args.run_dir),
                         manifest_path=Path(args.manifest), csv_path=Path(args.csv),
                         questions_path=Path(args.questions), references_path=Path(args.references),
                         dev_gold_path=Path(args.dev_gold))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "out": str(out),
                      "extraction_joint_micro_f1": report["extraction"]["joint_micro_f1"],
                      "strict_primary_success": {
                          method: sum(item["primary_success"] for item in group["question_scores"])
                          for method, group in report["methods"].items()},
                      "bounded_alias_primary_success": {
                          method: sum(item["primary_success"] for item in group["question_scores"])
                          for method, group in report["methods_bounded_aliases_v1"].items()},
                      "questions_per_method": len(report["methods"]["a"]["question_scores"])},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
