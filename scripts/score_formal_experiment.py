"""Offline, hash-bound scoring of a completed or partial formal Runner journal."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from eval.metrics import score_answer
from eval.questions import GoldReference, QuestionCandidate
from scripts.run_formal_experiment import FormalInputs, checked_plan
from src.data_loader import dataset_fingerprint, load_csv
from src.schemas import AnswerPayload, Category, ExtractionDataset, RecordSet
from src.semeval import CandidateSplit

METHODS = ("a", "b", "c")
TASK_TYPES = ("count", "rate", "selection", "comparison",
              "evidence_explanation", "insufficient_info")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("truncated run journal")
    rows = [json.loads(line) for line in raw.splitlines()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("invalid run journal row")
    return rows


def _tasks(plan: dict) -> list[str]:
    return [item for pack in plan["pack_ids"]
            for item in [f"{pack}:extract", *[
                f"{qid}:{method}" for qid in plan["question_ids"]
                if qid.startswith(f"{pack}-") for method in METHODS]]]


def _confirmed_references(plan: dict, inputs: FormalInputs, path: Path,
                          questions: dict[str, QuestionCandidate]) -> dict[str, GoldReference]:
    if inputs.release_path is None:
        raise ValueError("human freeze release is required")
    release = json.loads(inputs.release_path.read_text(encoding="utf-8"))
    if (release.get("status") != "FROZEN"
            or release.get("scoring_reference_status") != "HUMAN_CONFIRMED"
            or release.get("scoring_reference_sha256") != _sha(path)
            or release.get("scoring_reference_question_ids") != plan["question_ids"]):
        raise ValueError("human-confirmed final reference hash or identity is missing")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or len(raw) != 24:
        raise ValueError("final reference file must have 24 rows")
    refs = [GoldReference.model_validate(row) for row in raw]
    if ([ref.question_id for ref in refs] != plan["question_ids"]
            or any(ref.task_type != questions[ref.question_id].task_type for ref in refs)):
        raise ValueError("final references do not match frozen questions")
    for ref in refs:
        question = questions[ref.question_id]
        scope = set(question.record_ids)
        if ref.task_type == "count" and (type(ref.count) is not int or ref.count < 0):
            raise ValueError("final count reference is invalid")
        if ref.task_type == "rate":
            numerator, denominator = ref.numerator, ref.denominator
            if (type(numerator) is not int or type(denominator) is not int
                    or numerator < 0 or denominator < 0 or numerator > denominator
                    or (denominator == 0 and ref.rate is not None)
                    or (denominator > 0 and (ref.rate is None
                        or abs(ref.rate - numerator / denominator) > 0.001))):
                raise ValueError("final rate reference is inconsistent")
        for ids in (ref.selected_record_ids, ref.source_record_ids):
            if len(ids) != len(set(ids)) or not set(ids).issubset(scope):
                raise ValueError("final reference contains invalid record IDs")
        if ref.task_type == "insufficient_info" and not ref.insufficient_info:
            raise ValueError("final missing-information reference is invalid")
    return {ref.question_id: ref for ref in refs}


def _score_question(answer: AnswerPayload, reference: GoldReference,
                    question: QuestionCandidate, records: RecordSet, *, rubric: str) -> dict:
    if question.task_type == "rate" and question.rate_category != Category.SERVICE:
        # Locked metrics.py assumes service. Map only the question's fixed target
        # to that slot; all numeric and status checks remain unchanged.
        target = question.rate_category
        if target is None:
            raise ValueError("rate question has no target category")
        converted = answer.model_copy(deep=True)
        claims = []
        for claim in converted.numeric_claims:
            if claim.category != target:
                continue
            if rubric == "bounded_aliases_v1":
                words = set(re.findall(r"[a-z]+", claim.metric.casefold()))
                other = {"food", "service", "price", "ambience"} - {target.value}
                if words & other:
                    continue
                claim.metric = re.sub(rf"\b{re.escape(target.value)}\b", "service",
                                      claim.metric, flags=re.IGNORECASE)
            claim.category = Category.SERVICE
            claims.append(claim)
        converted.numeric_claims = claims
        return score_answer(converted, reference, records.records, metric_rubric=rubric)
    return score_answer(answer, reference, records.records, metric_rubric=rubric)


def _call_audit(path: Path, plan: dict, task_ids: list[str]) -> dict:
    rows = _jsonl(path)
    if len(rows) > 2 * plan["max_api_requests"]:
        raise ValueError("call ledger exceeds request ceiling")
    by_task: Counter[str] = Counter()
    task_entries: dict[str, list[dict]] = defaultdict(list)
    responses_by_task: dict[str, list[dict]] = defaultdict(list)
    groups: dict[str, list[dict]] = defaultdict(list)
    anomalies: list[str] = []
    calls = 0
    last_task_index = -1
    for index in range(0, len(rows), 2):
        begin = rows[index]
        task = begin.get("task_id")
        if (begin.get("event") != "begin" or begin.get("call_id") != calls + 1
                or task not in task_ids or begin.get("pack_id") != task[:3]
                or _json_sha(begin.get("request")) != begin.get("request_sha256")):
            raise ValueError("call request identity or hash mismatch")
        position = task_ids.index(task)
        if position < last_task_index or not isinstance(begin.get("stage"), str):
            raise ValueError("call ledger is out of task order")
        last_task_index = position
        if task.endswith(":extract"):
            if begin.get("method") != "shared_extraction" or begin.get("question_id") is not None:
                raise ValueError("shared extraction call context differs")
            group = "shared_extraction"
        else:
            qid, method = task.rsplit(":", 1)
            if begin.get("method") != method or begin.get("question_id") != qid:
                raise ValueError("method call context differs from task")
            group = method
        payload = begin["request"].get("payload", {})
        if any(key in payload for key in ("gold", "reference", "reference_json", "expected_answer")):
            raise ValueError("reference data appeared in model request")
        calls += 1
        by_task[task] += 1
        if index + 1 == len(rows):
            anomalies.append("unmatched_request")
            unknown = {"outcome": "unknown"}
            groups[group].append(unknown)
            task_entries[task].append(unknown)
            break
        end = rows[index + 1]
        fields = ("call_id", "task_id", "pack_id", "question_id", "method", "stage", "request_sha256")
        if (end.get("event") != "end" or any(begin.get(k) != end.get(k) for k in fields)
                or end.get("outcome") not in {"response", "error"}):
            raise ValueError("call begin/end mismatch")
        if end["outcome"] == "response":
            if (end.get("response_model") != plan["model"]
                    or _json_sha(end.get("response")) != end.get("response_sha256")):
                raise ValueError("call response model or hash mismatch")
            responses_by_task[task].append(end)
        else:
            anomalies.append("transport_error")
        groups[group].append(end)
        task_entries[task].append(end)
    if calls > plan["max_api_requests"]:
        raise ValueError("actual requests exceed ceiling")

    def totals(items: list[dict]) -> dict:
        def summed(field: str):
            values = [item.get(field) for item in items]
            valid = all(type(v) is int and v >= 0 for v in values) if field.endswith("tokens") else (
                all(type(v) in (int, float) and v >= 0 for v in values))
            return sum(values) if valid else None
        inp, out = summed("input_tokens"), summed("output_tokens")
        cost = None if inp is None or out is None else (
            Decimal(inp) * Decimal(plan["input_usd_per_million"]) +
            Decimal(out) * Decimal(plan["output_usd_per_million"])) / Decimal(1_000_000)
        return {"requests": len(items), "input_tokens": inp, "output_tokens": out,
                "latency_ms": summed("latency_ms"),
                "estimated_cost_usd": str(cost) if cost is not None else None,
                "failed_calls": sum(item.get("outcome") != "response" for item in items)}

    all_items = [item for chunk in groups.values() for item in chunk]
    overall = totals(all_items)
    if calls and (overall["input_tokens"] is None or overall["output_tokens"] is None):
        anomalies.append("unknown_token_usage")
    if calls and overall["latency_ms"] is None:
        anomalies.append("unknown_latency")
    return {"by_task": by_task, "task_entries": task_entries,
            "responses_by_task": responses_by_task,
            "overall": overall,
            "by_group": {name: totals(groups[name]) for name in ("shared_extraction", *METHODS)},
            "anomalies": anomalies}


def _run_audit(run_dir: Path, plan: dict, inputs: FormalInputs,
               questions: dict[str, QuestionCandidate]) -> tuple[list[dict], dict, dict]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    tasks = _tasks(plan)
    if (manifest.get("plan") != plan or manifest.get("task_ids") != tasks
            or manifest.get("gold_used_by_model") is not False
            or manifest.get("mode") not in {"LIVE", "INJECTED_OFFLINE"}
            or summary.get("plan_sha256") != plan["plan_sha256"]
            or summary.get("mode") != manifest["mode"]
            or summary.get("planned_tasks") != 76
            or summary.get("planned_method_answers") != 72):
        raise ValueError("run manifest or summary differs from frozen plan")
    split = CandidateSplit.model_validate_json(inputs.split_path.read_text(encoding="utf-8"))
    source = {r.record_id: r for r in load_csv(inputs.test_csv, preserve_explicit_ids=True).records}
    pack_records = {pack: RecordSet(records=[source[rid] for rid in split.packs[int(pack[1:]) - 1]])
                    for pack in plan["pack_ids"]}
    fingerprints = {pack: dataset_fingerprint(records) for pack, records in pack_records.items()}
    events = _jsonl(run_dir / "tasks.jsonl")
    finished: dict[str, dict] = {}
    active: str | None = None
    failed_seen = False
    for event in events:
        task = event.get("task_id")
        if (event.get("event") == "begin" and active is None and not failed_seen
                and len(finished) < len(tasks) and task == tasks[len(finished)]):
            active = task
        elif event.get("event") in {"complete", "failed"} and task == active:
            finished[task] = event
            failed_seen = event["event"] == "failed"
            active = None
        else:
            raise ValueError("task journal has duplicate or out-of-order task")
    for task, event in finished.items():
        if task.endswith(":extract"):
            pack = task[:3]
            path = run_dir / "extractions" / f"{pack}.json"
            if not path.is_file() or _sha(path) != event.get("artifact_sha256"):
                raise ValueError("shared extraction artifact hash mismatch")
            extraction = ExtractionDataset.model_validate_json(path.read_text(encoding="utf-8"))
            if (extraction.records != pack_records[pack].records
                    or extraction.fingerprint != fingerprints[pack]
                    or extraction.provider_model != plan["model"]
                    or extraction.prompt_version != plan["prompt_versions"]["extraction"]):
                raise ValueError("shared extraction source/model/Prompt differs")
    rows = _jsonl(run_dir / "results.jsonl")
    expected = [task for task in finished if not task.endswith(":extract")]
    if [row.get("task_id") for row in rows] != expected:
        raise ValueError("result rows are missing, duplicated or reordered")
    for row in rows:
        task = row["task_id"]
        event = finished[task]
        qid, method = task.rsplit(":", 1)
        pack = questions[qid].pack_id
        extraction_hash = (_sha(run_dir / "extractions" / f"{pack}.json")
                           if method != "a" else None)
        if (row.get("question_id") != qid or row.get("pack_id") != pack
                or row.get("method") != method or _json_sha(row) != event.get("artifact_sha256")
                or row.get("source_sha256") != fingerprints[pack]
                or row.get("shared_extraction_sha256") != extraction_hash
                or type(row.get("requests")) is not int or row["requests"] < 0):
            raise ValueError("result identity, source or hash mismatch")
        if event["event"] == "failed":
            if row.get("status") != "execution_error" or "answer" in row:
                raise ValueError("failed task result shape differs")
        else:
            answer = AnswerPayload.model_validate(row.get("answer"))
            if (row.get("status") != answer.status or answer.method != method
                    or answer.question_id != qid
                    or answer.usage.get("api_requests") != row["requests"]):
                raise ValueError("answer identity, status or request count mismatch")
    calls = _call_audit(run_dir / "calls.jsonl", plan, tasks)
    if any(task not in finished and task != active for task in calls["by_task"]):
        raise ValueError("model call belongs to a task never started")
    overall = calls["overall"]
    reported_cost = summary.get("estimated_cost_usd")
    computed_cost = overall["estimated_cost_usd"]
    try:
        costs_agree = (reported_cost is None and computed_cost is None) or (
            reported_cost is not None and computed_cost is not None
            and Decimal(reported_cost) == Decimal(computed_cost))
    except (InvalidOperation, TypeError):
        costs_agree = False
    if (summary.get("recorded_requests") != overall["requests"]
            or summary.get("input_tokens") != overall["input_tokens"]
            or summary.get("output_tokens") != overall["output_tokens"]
            or not costs_agree
            or summary.get("completed_tasks") != sum(e["event"] == "complete" for e in finished.values())
            or summary.get("completed_method_answers") != sum(
                not task.endswith(":extract") and e["event"] == "complete"
                for task, e in finished.items())
            or summary.get("recorded_answer_status_counts") != dict(Counter(
                row["status"] for row in rows))):
        raise ValueError("run summary disagrees with journals")
    if (summary.get("status") not in {"COMPLETE", "PAUSED", "PARTIAL"}
            or (computed_cost is not None
                and Decimal(computed_cost) > Decimal(plan["max_cost_usd"]))):
        raise ValueError("run status or cost cap is invalid")
    for row in rows:
        if calls["by_task"][row["task_id"]] != row["requests"]:
            raise ValueError("answer request count differs from ledger")
        if "answer" in row:
            entries = calls["task_entries"].get(row["task_id"], [])
            for field in ("input_tokens", "output_tokens"):
                values = [item.get(field) for item in entries]
                known = all(type(value) is int and value >= 0 for value in values)
                total = sum(values) if known else None
                if row["answer"].get("usage", {}).get(field) != total:
                    raise ValueError("answer Token usage differs from call ledger")
        if row["status"] == "ok":
            responses = [event for event in calls["responses_by_task"].get(row["task_id"], [])
                         if event["stage"] in {"direct_answer", "answer", "answer_repair"}]
            if responses:
                raw_answer = responses[-1]["response"]
                original = AnswerPayload.model_validate({**raw_answer, "method": row["method"],
                                                         "question_id": row["question_id"]})
                answer = AnswerPayload.model_validate(row["answer"])
                if any(getattr(answer, field) != getattr(original, field) for field in (
                        "status", "answer_text", "numeric_claims", "selected_record_ids",
                        "comparison_groups", "citations", "denominator_explanation")):
                    raise ValueError("answer differs from final recorded model response")
    for task, event in finished.items():
        if event["event"] == "complete" and event.get("requests") != calls["by_task"][task]:
            raise ValueError("completed task requests differ from ledger")
    all_complete = len(finished) == 76 and all(e["event"] == "complete" for e in finished.values())
    if (summary.get("status") == "COMPLETE") != all_complete:
        raise ValueError("run completion status differs from tasks")
    if active:
        calls["anomalies"].append("in_flight_task")
    if any(e["event"] == "failed" for e in finished.values()):
        calls["anomalies"].append("failed_task")
    return rows, {"summary": summary, "mode": manifest["mode"], "pack_records": pack_records}, calls


def _outcome(row: dict | None, question: QuestionCandidate, score: dict | None) -> str:
    if row is None:
        return "missing"
    if row["status"] == "execution_error":
        return "run_error"
    if row["status"] == "insufficient_info":
        return "valid_refusal" if question.task_type == "insufficient_info" else "false_refusal"
    if row["status"] == "failed":
        return "model_failure"
    if row["status"] == "partial":
        return "partial"
    if row["status"] == "clarification":
        return "clarification"
    return "correct" if score and score["primary_success"] else "incorrect"


def score_formal_run(*, plan_path: Path, inputs: FormalInputs, run_dir: Path,
                     final_references_path: Path) -> dict:
    plan = checked_plan(plan_path, inputs, resume=True)
    if run_dir.resolve() != Path(plan["planned_run_directory"]).resolve():
        raise ValueError("run directory differs from plan")
    raw = json.loads(inputs.questions_path.read_text(encoding="utf-8"))
    selected = [QuestionCandidate.model_validate(item) for item in raw
                if item["question_id"] in plan["question_ids"]]
    if [q.question_id for q in selected] != plan["question_ids"]:
        raise ValueError("scoring question IDs differ")
    questions = {q.question_id: q for q in selected}
    refs = _confirmed_references(plan, inputs, final_references_path, questions)
    rows, runtime, calls = _run_audit(run_dir, plan, inputs, questions)
    by_key = {(row["question_id"], row["method"]): row for row in rows}
    answer_rows = []
    paired = []
    for question in selected:
        pair = {"question_id": question.question_id, "pack_id": question.pack_id,
                "task_type": question.task_type}
        for method in METHODS:
            row = by_key.get((question.question_id, method))
            primary = diagnostic = None
            if row and row["status"] != "execution_error":
                answer = AnswerPayload.model_validate(row["answer"])
                primary = _score_question(answer, refs[question.question_id], question,
                                          runtime["pack_records"][question.pack_id],
                                          rubric=plan["scoring_rule_version"])
                if plan["scoring_rule_version"] == "strict":
                    diagnostic = _score_question(answer, refs[question.question_id], question,
                                                 runtime["pack_records"][question.pack_id],
                                                 rubric="bounded_aliases_v1")
            outcome = _outcome(row, question, primary)
            item = {"question_id": question.question_id, "pack_id": question.pack_id,
                    "task_type": question.task_type, "method": method,
                    "answer_status": row["status"] if row else "missing",
                    "outcome": outcome, "correct": bool(primary and primary["primary_success"]),
                    "requests": row["requests"] if row else None,
                    "false_refusal": bool(primary and primary["false_refusal"]),
                    "selection_f1": primary["selection_f1"] if primary else None,
                    "alias_diagnostic_correct": (diagnostic["primary_success"]
                                                 if diagnostic else None)}
            answer_rows.append(item)
            pair[f"{method}_correct"] = item["correct"]
            pair[f"{method}_outcome"] = outcome
        paired.append(pair)
    methods = {}
    for method in METHODS:
        items = [row for row in answer_rows if row["method"] == method]
        by_type = {task: {"correct": sum(r["correct"] for r in items if r["task_type"] == task),
                          "denominator": 4} for task in TASK_TYPES}
        for value in by_type.values():
            value["accuracy"] = value["correct"] / 4
        correct = sum(row["correct"] for row in items)
        methods[method] = {"correct": correct, "denominator": 24,
                           "accuracy": correct / 24, "by_task_type": by_type,
                           "outcomes": dict(Counter(row["outcome"] for row in items)),
                           "alias_diagnostic_correct": sum(
                               row["alias_diagnostic_correct"] is True for row in items)}
    source_hashes = {"plan": _sha(plan_path), "release": _sha(inputs.release_path),
                     "final_references": _sha(final_references_path),
                     **{name: _sha(run_dir / name) if (run_dir / name).exists() else None for name in
                        ("run_manifest.json", "summary.json", "tasks.jsonl", "calls.jsonl", "results.jsonl")}}
    status = ("SYNTHETIC_DIAGNOSTIC" if runtime["mode"] != "LIVE" else
              "FORMAL_SCORE" if runtime["summary"]["status"] == "COMPLETE"
              and not calls["anomalies"] else "INCOMPLETE_RUN_DIAGNOSTIC")
    return {"status": status, "run_mode": runtime["mode"],
            "formal_score": status == "FORMAL_SCORE",
            "scoring_rule_version": plan["scoring_rule_version"],
            "alias_diagnostic_is_primary": False,
            "plan_sha256": plan["plan_sha256"], "source_sha256": source_hashes,
            "sample_size_note": "24 questions per method; four per task type. Descriptive rates only; small sample.",
            "methods": methods, "per_answer": answer_rows, "paired_questions": paired,
            "outcome_counts": dict(Counter(row["outcome"] for row in answer_rows)),
            "calls": {"request_ceiling": plan["max_api_requests"],
                      "overall": calls["overall"], "by_group": calls["by_group"],
                      "anomalies": calls["anomalies"],
                      "shared_extraction_counted_once": True},
            "run_status": runtime["summary"]["status"]}


def write_report(report: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")
    for filename, key in (("per_answer.csv", "per_answer"),
                          ("paired_questions.csv", "paired_questions")):
        rows = report[key]
        with (out_dir / filename).open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = ["# Formal experiment score table", "",
             f"Status: `{report['status']}`. Run mode: `{report['run_mode']}`.", "",
             "| Method | Correct | Denominator | Accuracy |", "|---|---:|---:|---:|"]
    for method in METHODS:
        item = report["methods"][method]
        lines.append(f"| {method.upper()} | {item['correct']} | 24 | {item['accuracy']:.3f} |")
    lines += ["", "| Task type | A | B | C |", "|---|---:|---:|---:|"]
    for task in TASK_TYPES:
        values = [report["methods"][method]["by_task_type"][task] for method in METHODS]
        lines.append(f"| {task} | " + " | ".join(
            f"{value['correct']}/{value['denominator']}" for value in values) + " |")
    calls = report["calls"]
    lines += ["", f"Requests: {calls['overall']['requests']}/{calls['request_ceiling']}; "
              "shared ABSA extraction counted once.",
              "Unknown usage or cost is shown as null in summary.json.", "",
              report["sample_size_note"], "",
              "Per-answer and paired-question rows are in the CSV files. "
              "A synthetic or incomplete run is not a formal result.", ""]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline formal scorer; no model calls")
    for name in ("plan", "run-dir", "final-references", "out-dir",
                 "reviewer-1", "reviewer-2", "adjudication", "release"):
        parser.add_argument(f"--{name}", required=True)
    defaults = {"lock": "configs/formal_24_candidate.lock.json",
                "split": "data/processed/candidate_split.json",
                "test-csv": "data/processed/test.csv", "dev-csv": "data/processed/dev.csv",
                "questions": "data/processed/candidate_questions.json",
                "references": "data/gold/candidate_references.json",
                "test-gold": "data/gold/test.json", "metrics-code": "eval/metrics.py"}
    for name, default in defaults.items():
        parser.add_argument(f"--{name}", default=default)
    args = parser.parse_args(argv)
    inputs = FormalInputs(
        lock_path=Path(args.lock), split_path=Path(args.split),
        test_csv=Path(args.test_csv), dev_csv=Path(args.dev_csv),
        questions_path=Path(args.questions), references_path=Path(args.references),
        test_gold_path=Path(args.test_gold), metrics_path=Path(args.metrics_code),
        reviewer_1_path=Path(args.reviewer_1), reviewer_2_path=Path(args.reviewer_2),
        adjudication_path=Path(args.adjudication), release_path=Path(args.release))
    try:
        out_dir = Path(args.out_dir)
        if Path("outputs").resolve() not in out_dir.resolve().parents:
            raise ValueError("report output must be inside ignored outputs/")
        report = score_formal_run(plan_path=Path(args.plan), inputs=inputs,
                                  run_dir=Path(args.run_dir),
                                  final_references_path=Path(args.final_references))
        write_report(report, out_dir)
        print(json.dumps({"status": report["status"], "out_dir": str(out_dir),
                          "network_calls_made": 0}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"formal offline score refused: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
