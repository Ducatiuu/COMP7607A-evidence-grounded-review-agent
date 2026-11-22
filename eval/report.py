"""Independent, actual-row aggregation. MOCK rows stay visibly diagnostic."""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from .metrics import score_answer, summarize_question_scores
from .questions import GoldReference
from .runner import RunManifest, RunRow


def summarize_runs(run_dirs: list[str | Path], references: list[GoldReference]) -> dict:
    by_reference = {item.question_id: item for item in references}
    if len(by_reference) != len(references):
        raise ValueError("duplicate gold reference ID")
    groups = {}
    task_hashes = {}
    for directory in map(Path, run_dirs):
        manifest = RunManifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))
        key = (manifest.config.condition, manifest.config.method)
        if key in groups:
            raise ValueError("duplicate condition/method run")
        if key[0] in task_hashes and task_hashes[key[0]] != manifest.tasks_sha256:
            raise ValueError("paired methods have different task manifests")
        task_hashes[key[0]] = manifest.tasks_sha256
        if not set(manifest.task_keys).issubset({json.dumps([ref_id, index], separators=(",", ":"))
                                                   for ref_id in by_reference for index in range(3)}):
            raise ValueError("run has a question without a gold reference")
        latest: dict[str, RunRow] = {}
        for line in (directory / "answers.jsonl").read_text(encoding="utf-8").splitlines():
            row = RunRow.model_validate_json(line)
            if (row.config_sha256 != manifest.config_sha256 or row.key not in manifest.task_keys
                    or row.method != key[1] or row.condition != key[0]):
                raise ValueError("row does not match manifest")
            if row.key in latest and row.attempt_index != latest[row.key].attempt_index + 1:
                raise ValueError("nonconsecutive attempts")
            latest[row.key] = row
        scores = [score_answer(row.answer, by_reference[row.question_id]) for row in latest.values()]
        success_by_key = {row.key: bool(score_answer(row.answer, by_reference[row.question_id])["primary_success"])
                          for row in latest.values()}
        groups[key] = {
            "condition": key[0], "method": key[1], "expected": len(manifest.task_keys),
            "recorded": len(latest), "missing": len(manifest.task_keys) - len(latest),
            "failed": sum(row.status in {"failed", "partial"} for row in latest.values()),
            "api_requests_known": sum(row.api_requests or 0 for row in latest.values() if row.api_requests is not None),
            "api_requests_unknown_rows": sum(row.api_requests is None for row in latest.values()),
            "cost_usd": None if not latest or any(row.cost_usd is None for row in latest.values()) else sum(row.cost_usd for row in latest.values()),
            "scores": summarize_question_scores(scores),
            "rows": latest,
            "success_by_key": success_by_key,
        }
    paired = {}
    conditions: dict[str, list[str]] = defaultdict(list)
    for condition, method in groups:
        conditions[condition].append(method)
    for condition, methods in conditions.items():
        if len(methods) > 1:
            shared = set.intersection(*(set(groups[(condition, method)]["rows"]) for method in methods))
            rates = {method: sum(groups[(condition, method)]["success_by_key"][item] for item in shared) / len(shared) if shared else None
                     for method in sorted(methods)}
            deltas = {f"{right}-minus-{left}": rates[right] - rates[left] if shared else None
                      for left, right in combinations(sorted(methods), 2)}
            paired[condition] = {"methods": sorted(methods), "question_repeat_keys": sorted(shared),
                                 "count": len(shared), "paired_success_rate": rates, "paired_success_delta": deltas}
    if ("main", "c") in groups and ("ablation", "c") in groups:
        shared = set(groups[("main", "c")]["rows"]) & set(groups[("ablation", "c")]["rows"])
        main_rate = sum(groups[("main", "c")]["success_by_key"][item] for item in shared) / len(shared) if shared else None
        ablation_rate = sum(groups[("ablation", "c")]["success_by_key"][item] for item in shared) / len(shared) if shared else None
        paired["main_vs_ablation_c"] = {"methods": ["c_main", "c_ablation"],
                                          "question_repeat_keys": sorted(shared), "count": len(shared),
                                          "paired_success_rate": {"c_main": main_rate, "c_ablation": ablation_rate},
                                          "paired_success_delta": ablation_rate - main_rate if shared else None}
    repeat_variability = {}
    for (condition, method), group in groups.items():
        if condition != "repeats":
            continue
        by_question = defaultdict(list)
        for row in group["rows"].values():
            by_question[row.question_id].append(row)
        complete_pairs = [rows for rows in by_question.values() if {row.repeat_index for row in rows} == {1, 2}]
        repeat_variability[method] = {
            "complete_question_pairs": len(complete_pairs),
            "status_disagreement_count": sum(rows[0].status != rows[1].status for rows in complete_pairs),
            "primary_success_disagreement_count": sum(
                group["success_by_key"][rows[0].key] != group["success_by_key"][rows[1].key]
                for rows in complete_pairs),
            "incomplete_question_pairs": len(by_question) - len(complete_pairs),
        }
    summaries = []
    for group in groups.values():
        summaries.append({key: value for key, value in group.items() if key not in {"rows", "success_by_key"}})
    return {"mode": "MOCK_ONLY_NOT_RESEARCH_RESULT", "runs": summaries,
            "paired": paired, "repeat_variability": repeat_variability}
