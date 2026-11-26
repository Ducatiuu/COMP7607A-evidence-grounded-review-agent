"""Versioned final-material preflight for owner-adjudicated four-Pack experiments.

This module only reads files and builds a plan. It never constructs a provider.
The original candidate lock and both original reviewer sheets remain untouched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from eval.question_audit import audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate
from scripts.audit_formal_freeze import audit_freeze, file_sha, read_items
from scripts.plan_formal_experiment import build_plan


PROMPT_SOURCES = {
    "extraction": "src/absa_service/extractor.py",
    "query": "src/controllers/query_parser.py",
    "answer": "src/verification/repair.py",
    "decision": "src/controllers/dynamic_agent.py",
    "direct": "src/controllers/direct_llm.py",
}


def _json_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _local_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("final lock references a missing or external local file")
    return path


def build_final_plan(**kwargs) -> dict:
    """Rebuild original review checks, then verify every final revision and release."""
    lock_path: Path = kwargs["lock_path"]
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if (lock.get("schema_version") != 2 or lock.get("status") != "OWNER_CONFIRMED_FINAL"
            or lock.get("project_root_relative_to_lock") != "../.."):
        raise ValueError("versioned final-material lock is invalid")
    root = (lock_path.resolve().parent / "../..").resolve()
    base_lock_path = _local_path(root, "configs/formal_24_candidate.lock.json")
    original_q_path = _local_path(root, "data/processed/candidate_questions.json")
    original_r_path = _local_path(root, "data/gold/candidate_references.json")
    if (file_sha(base_lock_path) != lock.get("original_lock_sha256")
            or file_sha(original_q_path) != lock.get("reviewed_source_sha256", {}).get("questions")
            or file_sha(original_r_path) != lock.get("reviewed_source_sha256", {}).get("references")):
        raise ValueError("reviewed original material hash mismatch")
    base_args = dict(kwargs, lock_path=base_lock_path, questions_path=original_q_path,
                     references_path=original_r_path, release_path=None,
                     adjudication_path=None)
    original_plan = build_plan(**base_args)
    if original_plan["question_review_state"] != "REVIEWED_AWAITING_ADJUDICATION_AND_FREEZE":
        raise ValueError("original independent human reviews are incomplete")
    if (original_plan["pack_ids"] != lock.get("pack_ids")
            or original_plan["question_ids"] != lock.get("question_ids")
            or original_plan["scoring_rule_version"] != lock.get("scoring_rule_version")
            or original_plan["prompt_versions"] != lock.get("prompt_versions")
            or original_plan["source_sha256"] != lock.get("reviewed_source_sha256")
            or original_plan["review_sheet_sha256"] != lock.get("review_sheet_sha256")):
        raise ValueError("final lock differs from reviewed original plan")
    expected_prompts = {name: file_sha(_local_path(root, relative))
                        for name, relative in PROMPT_SOURCES.items()}
    if lock.get("prompt_source_sha256") != expected_prompts:
        raise ValueError("versioned prompt source hash mismatch")
    owner_queue = _local_path(root, lock["owner_queue_path"])
    owner_status = _local_path(root, lock["owner_status_path"])
    selected_q_path = _local_path(root, lock["selected_questions_path"])
    selected_r_path = _local_path(root, lock["selected_references_path"])
    report = audit_freeze(root=root, reviewer_1=kwargs["reviewer_1_path"],
                          reviewer_2=kwargs["reviewer_2_path"],
                          adjudication_queue=owner_queue,
                          adjudication_status=owner_status,
                          final_questions=selected_q_path,
                          final_references=selected_r_path,
                          versioned_release=True)
    if report["blockers"] or report["review"]["attention_question_ids"] != lock.get("adjudicated_question_ids"):
        raise ValueError("owner adjudication or final-material audit is incomplete")
    if (file_sha(owner_queue) != lock.get("owner_queue_sha256")
            or file_sha(owner_status) != lock.get("owner_status_sha256")
            or file_sha(selected_q_path) != lock.get("selected_questions_file_sha256")
            or file_sha(selected_r_path) != lock.get("selected_references_file_sha256")
            or report["hashes"]["selected_final_questions"] != lock.get("selected_questions_sha256")
            or report["hashes"]["selected_final_references"] != lock.get("selected_references_sha256")):
        raise ValueError("final owner decision or selected material hash mismatch")
    final_paths = {"split": kwargs["split_path"], "test_csv": kwargs["test_csv"],
                   "dev_csv": kwargs["dev_csv"], "questions": kwargs["questions_path"],
                   "references": kwargs["references_path"],
                   "test_gold": kwargs["test_gold_path"],
                   "metrics_code": kwargs["metrics_path"]}
    final_source_hashes = {name: file_sha(path) for name, path in final_paths.items()}
    if final_source_hashes != lock.get("source_sha256"):
        raise ValueError("final source file hash mismatch")
    original_all_q = read_items(original_q_path, QuestionCandidate)
    final_all_q = read_items(kwargs["questions_path"], QuestionCandidate)
    original_all_r = read_items(original_r_path, GoldReference)
    final_all_r = read_items(kwargs["references_path"], GoldReference)
    if (len(final_all_q) != 120 or len(final_all_r) != 120
            or [q.question_id for q in final_all_q] != [q.question_id for q in original_all_q]
            or [r.question_id for r in final_all_r] != [r.question_id for r in original_all_r]):
        raise ValueError("full final question/reference IDs differ from original")
    changed_q = [new.question_id for old, new in zip(original_all_q, final_all_q, strict=True)
                 if old != new]
    changed_r = [new.question_id for old, new in zip(original_all_r, final_all_r, strict=True)
                 if old != new]
    if (changed_q != lock.get("changed_question_ids")
            or changed_r != lock.get("changed_reference_ids")
            or changed_q != report["changed_question_ids"]
            or changed_r != report["changed_reference_ids"]):
        raise ValueError("final changes differ from owner-adjudicated scope")
    selected_q = [q for q in final_all_q if q.pack_id in lock["pack_ids"]]
    selected_r = [r for r in final_all_r if r.question_id in lock["question_ids"]]
    if (selected_q != read_items(selected_q_path, QuestionCandidate)
            or selected_r != read_items(selected_r_path, GoldReference)):
        raise ValueError("final full files and selected 24 files disagree")
    selected_audit = audit_candidate_questions(selected_q, selected_r, expected_packs=4)
    if (selected_audit["coverage_gaps"]
            or selected_audit["questions_sha256"] != lock["selected_questions_sha256"]
            or selected_audit["references_sha256"] != lock["selected_references_sha256"]):
        raise ValueError("final selected set fails coverage or hash checks")
    adjudication_path: Path | None = kwargs.get("adjudication_path")
    release_path: Path | None = kwargs.get("release_path")
    if adjudication_path is None or release_path is None:
        raise ValueError("final adjudication and signed release are required")
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    queue = json.loads(owner_queue.read_text(encoding="utf-8"))
    decisions = {row["question_id"]: {
        "final_decision": row["final_decision"],
        "decision_reason": row["decision_reason"],
        "adjudicator": row["adjudicator"],
        "adjudicated_at": row["adjudicated_at"],
        "revised_question_confirmed": row.get("revised_question_confirmed", False),
        "final_reference_confirmed": row.get("final_reference_confirmed", False),
    } for row in queue}
    signer = adjudication.get("adjudicator_id")
    if (adjudication.get("status") != "HUMAN_ADJUDICATED"
            or not isinstance(signer, str) or not signer.strip() or signer in {"R1", "R2"}
            or adjudication.get("resolved_question_ids") != lock["adjudicated_question_ids"]
            or adjudication.get("decisions") != decisions
            or {row["adjudicator"] for row in queue} != {signer}
            or adjudication.get("review_sheet_sha256") != lock["review_sheet_sha256"]
            or adjudication.get("owner_queue_sha256") != file_sha(owner_queue)
            or adjudication.get("owner_status_sha256") != file_sha(owner_status)
            or adjudication.get("selected_questions_sha256") != lock["selected_questions_sha256"]
            or adjudication.get("selected_references_sha256") != lock["selected_references_sha256"]):
        raise ValueError("final adjudication record does not bind owner decisions and reviewed files")
    release = json.loads(release_path.read_text(encoding="utf-8"))
    if (release.get("status") != "FROZEN"
            or release.get("signed_off_by") != signer
            or release.get("lock_sha256") != file_sha(lock_path)
            or release.get("pack_ids") != lock["pack_ids"]
            or release.get("question_ids") != lock["question_ids"]
            or release.get("source_sha256") != final_source_hashes
            or release.get("review_sheet_sha256") != lock["review_sheet_sha256"]
            or release.get("adjudication_sha256") != file_sha(adjudication_path)
            or release.get("owner_queue_sha256") != file_sha(owner_queue)
            or release.get("owner_status_sha256") != file_sha(owner_status)
            or release.get("selected_questions_sha256") != lock["selected_questions_sha256"]
            or release.get("selected_references_sha256") != lock["selected_references_sha256"]
            or release.get("scoring_reference_status") != "HUMAN_CONFIRMED"
            or release.get("scoring_reference_sha256") != file_sha(selected_r_path)
            or release.get("scoring_reference_question_ids") != lock["question_ids"]
            or release.get("scoring_rule_version") != lock["scoring_rule_version"]
            or release.get("provider") != "deepseek" or release.get("model") != "deepseek-flash"
            or release.get("prompt_versions") != lock["prompt_versions"]
            or release.get("prompt_source_sha256") != expected_prompts):
        raise ValueError("final freeze release does not bind the approved version")
    plan = dict(original_plan)
    plan.update(status="FROZEN_PREFLIGHT_READY", material_state="FROZEN",
                material_gate_passed=True, execution_permitted=False,
                formal_runner_implemented=True,
                lock_sha256=file_sha(lock_path), source_sha256=final_source_hashes,
                selected_questions_sha256=lock["selected_questions_sha256"],
                selected_references_sha256=lock["selected_references_sha256"],
                release_sha256=file_sha(release_path),
                max_question_chars=max(len(q.wording) for q in selected_q),
                prompt_source_sha256=expected_prompts,
                reviewed_source_sha256=lock["reviewed_source_sha256"],
                owner_queue_sha256=file_sha(owner_queue),
                owner_status_sha256=file_sha(owner_status))
    if plan["max_input_chars"] < plan["source_review_chars_max_pack"] + plan["max_question_chars"]:
        raise ValueError("final wording exceeds declared input character cap")
    plan["plan_sha256"] = _json_sha({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline final formal preflight; no provider or API key")
    parser.add_argument("--config", required=True, type=Path,
                        help="local JSON with build_plan paths and budget fields")
    parser.add_argument("--out", required=True, type=Path,
                        help="new ignored output plan; refuses overwrite")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        path_names = ("lock_path", "split_path", "test_csv", "dev_csv", "questions_path",
                      "references_path", "test_gold_path", "metrics_path", "reviewer_1_path",
                      "reviewer_2_path", "run_dir", "release_path", "adjudication_path")
        for name in path_names:
            config[name] = Path(config[name])
        plan = build_final_plan(**config)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("x", encoding="utf-8") as stream:
            json.dump(plan, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        print(json.dumps({"status": plan["status"], "material_state": plan["material_state"],
                          "execution_permitted": plan["execution_permitted"],
                          "network_calls_made": plan["network_calls_made"],
                          "plan_sha256": plan["plan_sha256"]}))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"final formal preflight refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
