"""Paired, Gold-only diagnosis of two completed development Pilots.

The references are unreviewed candidates. This module never calls a provider.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from eval.metrics import _counts_correct, _matching_claim
from eval.questions import GoldReference
from scripts.score_dev_pilot import score_pilot
from src.schemas import AnswerPayload, ExtractionDataset
from src.semeval import GoldRecord


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def error_types(answer: AnswerPayload, reference: GoldReference, records_by_id: dict[str, str]) -> list[str]:
    """Name observable mismatches to candidate references, not their human cause."""
    errors = []
    if reference.task_type == "insufficient_info":
        return [] if answer.status == "insufficient_info" else ["missing_expected_refusal"]
    if answer.status != "ok":
        errors.append("non_ok_status")
    if reference.task_type == "selection":
        if set(answer.selected_record_ids) != set(reference.selected_record_ids):
            errors.append("selection_set_mismatch")
    elif reference.task_type == "count":
        claim = _matching_claim(answer, "negative_count", "service", rubric="bounded_aliases_v1")
        if claim is None:
            errors.append("missing_recognized_count_claim")
        elif claim.value != reference.count:
            errors.append("count_value_mismatch")
    elif reference.task_type == "rate":
        claim = _matching_claim(answer, "negative_rate", "service", rubric="bounded_aliases_v1")
        if claim is None:
            errors.append("missing_recognized_rate_claim")
        else:
            if claim.numerator != reference.numerator:
                errors.append("rate_numerator_mismatch")
            if claim.denominator != reference.denominator:
                errors.append("rate_denominator_mismatch")
            if ((claim.value is None) != (reference.rate is None)
                    or (claim.value is not None and reference.rate is not None
                        and abs(claim.value - reference.rate) > 0.001)):
                errors.append("rate_value_mismatch")
            if not answer.denominator_explanation:
                errors.append("missing_denominator_explanation")
    elif reference.task_type in {"comparison", "evidence_explanation"}:
        if answer.comparison_groups != reference.comparison_groups:
            errors.append("comparison_groups_mismatch")
        if not _counts_correct(answer, reference, rubric="bounded_aliases_v1"):
            errors.append("category_counts_mismatch")
        if reference.task_type == "evidence_explanation":
            valid = ((not reference.source_record_ids and not answer.citations)
                     or bool(answer.citations) and all(
                         citation.record_id in reference.source_record_ids
                         and citation.record_id in records_by_id
                         and citation.quote in records_by_id[citation.record_id]
                         for citation in answer.citations))
            if not valid:
                errors.append("candidate_evidence_id_or_quote_mismatch")
    else:
        raise ValueError("unsupported task type")
    return errors


def compare(*, old_plan: Path, old_run: Path, new_plan: Path, new_run: Path,
            manifest: Path, csv_path: Path, questions: Path, references: Path,
            dev_gold: Path) -> tuple[dict, list[dict]]:
    inputs = {"manifest_path": manifest, "csv_path": csv_path,
              "questions_path": questions, "references_path": references,
              "dev_gold_path": dev_gold}
    old_score = score_pilot(plan_path=old_plan, run_dir=old_run, **inputs)
    new_score = score_pilot(plan_path=new_plan, run_dir=new_run, **inputs)
    if any(old_score["source_sha256"][field] != new_score["source_sha256"][field]
           for field in ("manifest", "csv", "questions", "references", "dev_gold")):
        raise ValueError("development data or references changed between Pilots")
    old_config, new_config = _json(old_plan), _json(new_plan)
    stable = ("provider", "model", "data_scope", "reasoning_effort", "extraction_prompt_version",
              "direct_prompt_version", "methods", "concurrency", "transport_retries",
              "record_count", "question_count", "max_input_chars", "max_api_requests",
              "max_input_tokens_per_request", "max_output_tokens_per_request",
              "timeout_seconds")
    if any(old_config[key] != new_config[key] for key in stable):
        raise ValueError("non-prompt experiment configuration differs")
    old_rows = [json.loads(line) for line in (old_run / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    new_rows = [json.loads(line) for line in (new_run / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    if len(old_rows) != len(new_rows) or any(
        (old["question_id"], old["method"]) != (new["question_id"], new["method"])
        for old, new in zip(old_rows, new_rows, strict=True)):
        raise ValueError("paired question/method rows differ")
    refs = {item.question_id: item for item in
            (GoldReference.model_validate(value) for value in _json(references))}
    old_extract = ExtractionDataset.model_validate(_json(old_run / "extractions.json"))
    new_extract = ExtractionDataset.model_validate(_json(new_run / "extractions.json"))
    if old_extract.records != new_extract.records:
        raise ValueError("extraction source records differ")
    source_text = {record.record_id: record.text for record in old_extract.records}
    gold = {item.record_id: item for item in
            (GoldRecord.model_validate(value) for value in _json(dev_gold))}
    changed_extractions = []
    for old_item, new_item in zip(old_extract.extractions, new_extract.extractions, strict=True):
        if old_item.record_id != new_item.record_id:
            raise ValueError("extraction IDs differ")
        old_labels = {(x.category.value, x.sentiment.value) for x in old_item.aspects}
        new_labels = {(x.category.value, x.sentiment.value) for x in new_item.aspects}
        if old_labels != new_labels:
            gold_labels = {(x.category.value, x.sentiment.value) for x in gold[old_item.record_id].aspects}
            changed_extractions.append({
                "record_id": old_item.record_id,
                "old_labels": sorted([list(x) for x in old_labels]),
                "new_labels": sorted([list(x) for x in new_labels]),
                "candidate_gold_labels": sorted([list(x) for x in gold_labels]),
                "old_joint_errors": len(old_labels ^ gold_labels),
                "new_joint_errors": len(new_labels ^ gold_labels),
            })
    paired = []
    for old_row, new_row in zip(old_rows, new_rows, strict=True):
        qid, method = old_row["question_id"], old_row["method"]
        index = next(i for i, item in enumerate(old_score["methods"][method]["question_scores"])
                     if item["question_id"] == qid)
        old_strict = old_score["methods"][method]["question_scores"][index]
        new_strict = new_score["methods"][method]["question_scores"][index]
        old_alias = old_score["methods_bounded_aliases_v1"][method]["question_scores"][index]
        new_alias = new_score["methods_bounded_aliases_v1"][method]["question_scores"][index]
        old_answer = AnswerPayload.model_validate(old_row["answer"])
        new_answer = AnswerPayload.model_validate(new_row["answer"])
        old_errors = error_types(old_answer, refs[qid], source_text)
        new_errors = error_types(new_answer, refs[qid], source_text)
        if old_alias["primary_success"] != (not old_errors) or new_alias["primary_success"] != (not new_errors):
            raise ValueError("diagnostic error types disagree with bounded scorer")
        paired.append({
            "question_id": qid, "task_type": refs[qid].task_type, "method": method,
            "old_status": old_answer.status, "new_status": new_answer.status,
            "old_strict_correct": old_strict["primary_success"],
            "new_strict_correct": new_strict["primary_success"],
            "old_bounded_correct": old_alias["primary_success"],
            "new_bounded_correct": new_alias["primary_success"],
            "old_error_types": old_errors, "new_error_types": new_errors,
            "old_selection_f1": old_alias["selection_f1"],
            "new_selection_f1": new_alias["selection_f1"],
            "old_claims": [claim.model_dump(mode="json") for claim in old_answer.numeric_claims],
            "new_claims": [claim.model_dump(mode="json") for claim in new_answer.numeric_claims],
            "old_comparison_groups": [[item.value for item in group] for group in old_answer.comparison_groups],
            "new_comparison_groups": [[item.value for item in group] for group in new_answer.comparison_groups],
            "old_selected_record_ids": old_answer.selected_record_ids,
            "new_selected_record_ids": new_answer.selected_record_ids,
            "old_citation_count": len(old_answer.citations),
            "new_citation_count": len(new_answer.citations),
        })
    method_summaries = {}
    for method in "abc":
        method_rows = [row for row in paired if row["method"] == method]
        method_summaries[method] = {
            "strict_correct": [sum(row[f"{version}_strict_correct"] for row in method_rows)
                               for version in ("old", "new")],
            "bounded_correct": [sum(row[f"{version}_bounded_correct"] for row in method_rows)
                                for version in ("old", "new")],
            "bounded_improved_questions": [row["question_id"] for row in method_rows
                                           if not row["old_bounded_correct"] and row["new_bounded_correct"]],
            "bounded_regressed_questions": [row["question_id"] for row in method_rows
                                            if row["old_bounded_correct"] and not row["new_bounded_correct"]],
        }
    report = {
        "status": "EXPLORATORY_DEV_PAIRED_COMPARISON_UNREVIEWED",
        "candidate_reference_review_complete": False, "formal_test_used": False,
        "causal_limit": "v8 and v9 reran extraction independently; changed extraction and stochastic A responses confound prompt-version effects",
        "source_sha256": {"old_plan": _sha(old_plan), "new_plan": _sha(new_plan),
                          "old_score_sources": old_score["source_sha256"],
                          "new_score_sources": new_score["source_sha256"]},
        "prompt_versions": {version: {key: config[key] for key in
                            ("extraction_prompt_version", "query_prompt_version",
                             "answer_prompt_version", "decision_prompt_version", "direct_prompt_version")}
                            for version, config in (("old", old_config), ("new", new_config))},
        "actual_requests": {"old": old_score["actual_requests"], "new": new_score["actual_requests"]},
        "run_usage": {version: {key: summary[key] for key in
                      ("actual_requests", "input_tokens", "output_tokens", "estimated_cost_usd")}
                      for version, summary in (("old", _json(old_run / "summary.json")),
                                               ("new", _json(new_run / "summary.json")))},
        "extraction": {"old": old_score["extraction"], "new": new_score["extraction"],
                       "changed_record_count": len(changed_extractions),
                       "changed_records": changed_extractions},
        "methods": method_summaries, "paired_rows": paired,
    }
    return report, paired


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline v8/v9 development Pilot comparison")
    parser.add_argument("--old-plan", required=True)
    parser.add_argument("--old-run", required=True)
    parser.add_argument("--new-plan", required=True)
    parser.add_argument("--new-run", required=True)
    parser.add_argument("--manifest", default="data/processed/dev_pilot/manifest.json")
    parser.add_argument("--csv", default="data/processed/dev_pilot/pilot.csv")
    parser.add_argument("--questions", default="data/processed/dev_pilot/questions.json")
    parser.add_argument("--references", default="data/gold/dev_pilot/references.json")
    parser.add_argument("--dev-gold", default="data/gold/dev.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--csv-out", required=True)
    args = parser.parse_args(argv)
    report, rows = compare(old_plan=Path(args.old_plan), old_run=Path(args.old_run),
                           new_plan=Path(args.new_plan), new_run=Path(args.new_run),
                           manifest=Path(args.manifest), csv_path=Path(args.csv),
                           questions=Path(args.questions), references=Path(args.references),
                           dev_gold=Path(args.dev_gold))
    out, csv_out = Path(args.out), Path(args.csv_out)
    if out.exists() or csv_out.exists():
        raise ValueError("comparison output already exists")
    out.parent.mkdir(parents=True, exist_ok=True)
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    fields = ("question_id", "task_type", "method", "old_status", "new_status",
              "old_strict_correct", "new_strict_correct", "old_bounded_correct",
              "new_bounded_correct", "old_error_types", "new_error_types",
              "old_selection_f1", "new_selection_f1", "old_claims", "new_claims",
              "old_comparison_groups", "new_comparison_groups", "old_selected_record_ids",
              "new_selected_record_ids", "old_citation_count", "new_citation_count")
    with csv_out.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row[field], ensure_ascii=False)
                             if isinstance(row[field], (list, dict)) else row[field]
                             for field in fields})
    print(json.dumps({"status": report["status"], "paired_rows": len(rows),
                      "changed_extraction_records": report["extraction"]["changed_record_count"],
                      "methods": report["methods"], "out": str(out), "csv_out": str(csv_out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
