"""Independent, actual-row aggregation. MOCK rows stay visibly diagnostic."""

from __future__ import annotations

import json
from collections import defaultdict
from itertools import combinations
from math import isfinite
from pathlib import Path

from src.schemas import ExtractionDataset, RecordSet

from .efficiency import ModelCallRow, latency_stats, summarize_model_calls
from .metrics import score_answer, summarize_question_scores
from .questions import GoldReference
from .runner import RunManifest, RunRow
from .shared_extraction import load_shared_extraction


def _host_wall_latency(row: RunRow, key: str) -> float | None:
    value = row.answer.usage.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"invalid {key} in answer usage")
    return float(value)


def summarize_runs(run_dirs: list[str | Path], references: list[GoldReference],
                   *, shared_extraction_dir: str | Path | None = None) -> dict:
    by_reference = {item.question_id: item for item in references}
    if len(by_reference) != len(references):
        raise ValueError("duplicate gold reference ID")
    groups = {}
    run_manifests: dict[tuple[str, str], RunManifest] = {}
    task_hashes = {}
    for directory in map(Path, run_dirs):
        manifest = RunManifest.model_validate_json((directory / "manifest.json").read_text(encoding="utf-8"))
        key = (manifest.config.condition, manifest.config.method)
        if key in groups:
            raise ValueError("duplicate condition/method run")
        run_manifests[key] = manifest
        if key[0] in task_hashes and task_hashes[key[0]] != manifest.tasks_sha256:
            raise ValueError("paired methods have different task manifests")
        task_hashes[key[0]] = manifest.tasks_sha256
        if not set(manifest.task_keys).issubset({json.dumps([ref_id, index], separators=(",", ":"))
                                                   for ref_id in by_reference for index in range(3)}):
            raise ValueError("run has a question without a gold reference")
        latest: dict[str, RunRow] = {}
        attempts: list[RunRow] = []
        for line in (directory / "answers.jsonl").read_text(encoding="utf-8").splitlines():
            row = RunRow.model_validate_json(line)
            if (row.config_sha256 != manifest.config_sha256 or row.key not in manifest.task_keys
                    or row.method != key[1] or row.condition != key[0]):
                raise ValueError("row does not match manifest")
            expected_attempt = latest[row.key].attempt_index + 1 if row.key in latest else 1
            if row.attempt_index != expected_attempt:
                raise ValueError("nonconsecutive attempts")
            latest[row.key] = row
            attempts.append(row)
        scores = [score_answer(row.answer, by_reference[row.question_id]) for row in latest.values()]
        success_by_key = {row.key: bool(score_answer(row.answer, by_reference[row.question_id])["primary_success"])
                          for row in latest.values()}
        api_requests_known = sum(row.api_requests for row in attempts if row.api_requests is not None)
        api_requests_unknown_rows = sum(row.api_requests is None for row in attempts)
        query_wall_times = [_host_wall_latency(row, "query_wall_latency_ms") for row in attempts]
        extraction_wall_times = [_host_wall_latency(row, "extraction_wall_latency_ms") for row in attempts]
        groups[key] = {
            "condition": key[0], "method": key[1], "expected": len(manifest.task_keys),
            "recorded": len(latest), "missing": len(manifest.task_keys) - len(latest),
            "failed": sum(row.status in {"failed", "partial"} for row in latest.values()),
            "attempt_rows": len(attempts),
            "failed_or_partial_attempt_rows": sum(row.status in {"failed", "partial"} for row in attempts),
            "api_requests_known": api_requests_known,
            "api_requests_unknown_rows": api_requests_unknown_rows,
            "cost_usd": None if not attempts or any(row.cost_usd is None for row in attempts) else sum(row.cost_usd for row in attempts),
            "attempt_wall_latency_ms": latency_stats([row.latency_ms for row in attempts]),
            "warm_query_wall_latency_ms": latency_stats([value for value in query_wall_times if value is not None]),
            "warm_query_latency_missing_attempts": sum(value is None for value in query_wall_times),
            "extraction_wall_latency_ms": latency_stats([value for value in extraction_wall_times if value is not None]),
            "model_call_efficiency": summarize_model_calls(
                directory / "model_calls.jsonl", config_sha256=manifest.config_sha256, method=key[1],
                task_keys=set(manifest.task_keys), answer_api_requests_known=api_requests_known,
                answer_api_requests_unknown_rows=api_requests_unknown_rows),
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
    report = {"mode": "MOCK_ONLY_NOT_RESEARCH_RESULT", "runs": summaries,
              "paired": paired, "repeat_variability": repeat_variability}
    if shared_extraction_dir is not None:
        if not {("main", "b"), ("main", "c")}.issubset(groups):
            raise ValueError("shared extraction report requires main B and C runs")
        shared_dir = Path(shared_extraction_dir)
        dataset_path = shared_dir / "dataset.json"
        if not dataset_path.is_file():
            raise ValueError("shared extraction artifact is incomplete")
        source = ExtractionDataset.model_validate_json(dataset_path.read_bytes())
        _, shared_hash, shared_manifest = load_shared_extraction(RecordSet(records=source.records), shared_dir)
        b_config = run_manifests[("main", "b")].config
        c_config = run_manifests[("main", "c")].config
        if (b_config.split != c_config.split or b_config.question_manifest_sha256 != c_config.question_manifest_sha256
                or b_config.prompt_version != c_config.prompt_version):
            raise ValueError("main B/C comparison configuration differs")
        method_queries = {}
        method_answer_requests = {}
        method_answer_unknown_rows = {}
        method_ledger_agreement = {}
        method_costs = {}
        for method in ("b", "c"):
            run_manifest = run_manifests[("main", method)]
            if (run_manifest.config.dataset_sha256 != shared_manifest.dataset_sha256
                    or run_manifest.config.condition_artifact_sha256 != shared_hash
                    or run_manifest.config.model_id != shared_manifest.provider_model):
                raise ValueError("main B/C runs are not bound to the shared extraction")
            group = groups[("main", method)]
            efficiency = group["model_call_efficiency"]
            if efficiency["available"] and efficiency["extraction_requests"]:
                raise ValueError("method run repeated shared extraction")
            method_queries[method] = efficiency["query_requests"] if efficiency["available"] else None
            method_answer_requests[method] = group["api_requests_known"]
            method_answer_unknown_rows[method] = group["api_requests_unknown_rows"]
            method_ledger_agreement[method] = efficiency.get("request_count_agrees")
            method_costs[method] = efficiency.get("cost_usd")
        setup_calls = [ModelCallRow.model_validate_json(line) for line in
                       (shared_dir / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()]
        setup_cost = None if any(call.cost_usd is None for call in setup_calls) else sum(call.cost_usd for call in setup_calls)
        report["shared_extraction"] = {
            "manifest_sha256": shared_hash, "dataset_sha256": shared_manifest.dataset_sha256,
            "setup_physical_requests": shared_manifest.requests,
            "setup_wall_latency_ms": shared_manifest.extraction_wall_latency_ms,
            "method_query_physical_requests": method_queries,
            "method_answer_requests_known": method_answer_requests,
            "method_answer_requests_unknown_rows": method_answer_unknown_rows,
            "method_ledger_agreement": method_ledger_agreement,
            "setup_cost_usd": setup_cost,
            "method_cost_usd": method_costs,
            "combined_physical_requests": None if any(value is None for value in method_queries.values())
                                          else shared_manifest.requests + sum(method_queries.values()),
            "cost_usd": None if setup_cost is None or any(value is None for value in method_costs.values())
                        else setup_cost + sum(method_costs.values()),
            "scope": "one shared setup plus main B/C observed calls; other conditions excluded",
        }
    return report
