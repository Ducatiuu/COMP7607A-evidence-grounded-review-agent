"""Export method-blinded answer packets; reviewer judgments remain empty."""

from __future__ import annotations

import csv
import json
import secrets
from pathlib import Path

from .runner import RunManifest, RunRow


def export_blind_review(run_dirs: list[str | Path], question_ids: list[str], output_dir: str | Path) -> dict:
    if not question_ids or len(question_ids) != len(set(question_ids)):
        raise ValueError("unique nonempty question IDs required")
    if len(run_dirs) != 3:
        raise ValueError("three method runs required")
    selected = set(question_ids)
    packets = []
    methods = set()
    for directory in map(Path, run_dirs):
        manifest = RunManifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.config.method in methods or manifest.config.condition != "main":
            raise ValueError("one main run per method required")
        methods.add(manifest.config.method)
        latest = {}
        for line in (directory / "answers.jsonl").read_text(encoding="utf-8").splitlines():
            row = RunRow.model_validate_json(line)
            if (row.config_sha256 != manifest.config_sha256 or row.key not in manifest.task_keys
                    or row.condition != "main" or row.method != manifest.config.method):
                raise ValueError("row/manifest mismatch")
            if row.repeat_index == 0 and row.question_id in selected:
                latest[row.question_id] = row
        if set(latest) != selected:
            raise ValueError("selected questions missing from a method run")
        for question_id in question_ids:
            packets.append((manifest.config.method, latest[question_id], str(directory)))
    if methods != {"a", "b", "c"}:
        raise ValueError("expected A/B/C runs")
    secrets.SystemRandom().shuffle(packets)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    review_path = output / "review_items.csv"
    mapping_path = output / "private_mapping.csv"
    if review_path.exists() or mapping_path.exists():
        raise ValueError("blind review export already exists; preserve the original mapping")
    with review_path.open("w", encoding="utf-8", newline="") as review, mapping_path.open("w", encoding="utf-8", newline="") as mapping:
        reviewer = csv.DictWriter(review, fieldnames=["blind_answer_id", "question_id", "answer_status", "answer_text",
                                                       "numeric_claims_json", "selected_record_ids_json", "comparison_groups_json", "citations_json"])
        private = csv.DictWriter(mapping, fieldnames=["blind_answer_id", "question_id", "method", "condition", "source_directory"])
        reviewer.writeheader()
        private.writeheader()
        for method, row, directory in packets:
            blind_id = secrets.token_hex(12)
            answer = row.answer
            reviewer.writerow({"blind_answer_id": blind_id, "question_id": row.question_id, "answer_status": row.status,
                               "answer_text": answer.answer_text,
                               "numeric_claims_json": json.dumps([item.model_dump(mode="json") for item in answer.numeric_claims]),
                               "selected_record_ids_json": json.dumps(answer.selected_record_ids),
                               "comparison_groups_json": json.dumps([[item.value for item in group] for group in answer.comparison_groups]),
                               "citations_json": json.dumps([item.model_dump(mode="json") for item in answer.citations])})
            private.writerow({"blind_answer_id": blind_id, "question_id": row.question_id, "method": method,
                              "condition": "main", "source_directory": directory})
    return {"review_items": len(packets), "questions": len(question_ids), "review_path": str(review_path),
            "private_mapping_path": str(mapping_path), "labels_written": 0}
