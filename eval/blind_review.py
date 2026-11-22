"""Export method-blinded answer packets; reviewer judgments remain empty."""

from __future__ import annotations

import csv
import json
import re
import secrets
from pathlib import Path

from .runner import RunManifest, RunRow


_METHOD_IDENTITY = re.compile(r"\b(?:method|system|approach|agent|workflow|pipeline)\s*[-_:#=]*\s*[abc]\b", re.IGNORECASE)
_PROCESS_IDENTITY = re.compile(
    r"\b(?:fixed[- ]workflow|dynamic[- ]agent|direct[- ]llm|tool[- ]trace|query[- ]parser|"
    r"aggregate_aspects|compare_aspects|filter_records|get_evidence)\b", re.IGNORECASE,
)


def _has_explicit_identity(row: RunRow) -> bool:
    """Flag recognizable method and process names in reviewer-visible fields."""
    answer = row.answer
    visible_text = [answer.answer_text]
    visible_text.extend(citation.quote for citation in answer.citations)
    visible_text.extend(citation.record_id for citation in answer.citations)
    visible_text.extend(claim.metric for claim in answer.numeric_claims)
    visible_text.extend(claim.unit for claim in answer.numeric_claims if claim.unit is not None)
    visible_text.extend(record_id for claim in answer.numeric_claims for record_id in claim.scope_ids)
    visible_text.extend(answer.selected_record_ids)
    return any(_METHOD_IDENTITY.search(value) or _PROCESS_IDENTITY.search(value) for value in visible_text)


def export_blind_review(run_dirs: list[str | Path], question_ids: list[str], output_dir: str | Path) -> dict:
    if (not question_ids or any(not isinstance(item, str) or not item.strip() for item in question_ids)
            or len(question_ids) != len(set(question_ids))):
        raise ValueError("unique nonempty question IDs required")
    if len(run_dirs) != 3:
        raise ValueError("three method runs required")
    selected = set(question_ids)
    packets = []
    methods = set()
    paired_config = None
    method_artifacts = {}
    for directory in map(Path, run_dirs):
        manifest = RunManifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.config.method in methods or manifest.config.condition != "main":
            raise ValueError("one main run per method required")
        methods.add(manifest.config.method)
        current_config = (manifest.tasks_sha256, tuple(manifest.task_keys), manifest.config.dataset_sha256,
                          manifest.config.question_manifest_sha256, manifest.config.split,
                          manifest.config.model_id, manifest.config.prompt_version)
        if paired_config is not None and current_config != paired_config:
            raise ValueError("paired run configuration differs")
        paired_config = current_config
        method_artifacts[manifest.config.method] = manifest.config.condition_artifact_sha256
        latest = {}
        last_attempt = {}
        for line in (directory / "answers.jsonl").read_text(encoding="utf-8").splitlines():
            row = RunRow.model_validate_json(line)
            if (row.config_sha256 != manifest.config_sha256 or row.key not in manifest.task_keys
                    or row.condition != "main" or row.method != manifest.config.method):
                raise ValueError("row/manifest mismatch")
            if row.attempt_index != last_attempt.get(row.key, 0) + 1:
                raise ValueError("nonconsecutive attempts in blind review source")
            last_attempt[row.key] = row.attempt_index
            if row.repeat_index == 0 and row.question_id in selected:
                latest[row.question_id] = row
        if set(latest) != selected:
            raise ValueError("selected questions missing from a method run")
        for question_id in question_ids:
            if _has_explicit_identity(latest[question_id]):
                raise ValueError(f"self-identifying answer text for {question_id}; manual blinding review required")
            packets.append((manifest.config.method, latest[question_id], str(directory)))
    if methods != {"a", "b", "c"}:
        raise ValueError("expected A/B/C runs")
    if method_artifacts["b"] != method_artifacts["c"]:
        raise ValueError("paired run configuration differs: B/C extraction artifacts")
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
