"""Candidate coverage gate; never treats automatic questions as human-approved."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict

from .questions import GoldReference, QuestionCandidate


TASK_TYPES = {"count", "rate", "selection", "comparison", "evidence_explanation", "insufficient_info"}
METADATA_TYPES = {"date", "rating", "customer_id"}


def _digest(items: list) -> str:
    serialized = json.dumps([item.model_dump(mode="json") for item in items], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def audit_candidate_questions(questions: list[QuestionCandidate], references: list[GoldReference],
                              *, expected_packs: int = 20, expected_pack_size: int = 30) -> dict:
    if not questions or expected_packs <= 0 or expected_pack_size <= 0:
        raise ValueError("questions and positive expected pack count/size are required")
    by_question = {item.question_id: item for item in questions}
    by_reference = {item.question_id: item for item in references}
    if (len(by_question) != len(questions) or len(by_reference) != len(references)
            or set(by_question) != set(by_reference)):
        raise ValueError("question/reference IDs must align uniquely")
    packs: dict[str, list[QuestionCandidate]] = defaultdict(list)
    for question in questions:
        if by_reference[question.question_id].task_type != question.task_type:
            raise ValueError("question/reference task type mismatch")
        packs[question.pack_id].append(question)
    pack_issues = {pack_id: sorted(TASK_TYPES - {item.task_type for item in items})
                   for pack_id, items in packs.items()
                   if len(items) != 6 or {item.task_type for item in items} != TASK_TYPES}
    scope_issues = [pack_id for pack_id, items in packs.items()
                    if any(item.record_ids != items[0].record_ids or len(item.record_ids) != expected_pack_size
                           or len(set(item.record_ids)) != expected_pack_size for item in items)]
    pack_records = [item[0].record_ids for item in packs.values()]
    all_records = [record_id for ids in pack_records for record_id in ids]
    cross_pack_overlap = len(all_records) != len(set(all_records))
    metadata = {item.metadata_required for item in questions if item.task_type == "insufficient_info"
                and item.metadata_required is not None}
    selection_refs = [by_reference[item.question_id] for item in questions if item.task_type == "selection"]
    rate_refs = [by_reference[item.question_id] for item in questions if item.task_type == "rate"]
    comparison_refs = [by_reference[item.question_id] for item in questions
                       if item.task_type in {"comparison", "evidence_explanation"}]
    evidence = {
        "empty_selection": sum(not item.selected_record_ids for item in selection_refs),
        "nonempty_selection": sum(bool(item.selected_record_ids) for item in selection_refs),
        "undefined_rate": sum(item.denominator == 0 and item.rate is None for item in rate_refs),
        "comparison_tie": sum(bool(item.comparison_groups) and len(item.comparison_groups[0]) > 1
                              for item in comparison_refs),
    }
    gaps = []
    if len(packs) != expected_packs:
        gaps.append("pack_count")
    if pack_issues:
        gaps.append("six_types_per_pack")
    if scope_issues:
        gaps.append("pack_scope_alignment")
    if cross_pack_overlap:
        gaps.append("cross_pack_overlap")
    gaps.extend(key for key, value in evidence.items() if value == 0)
    if metadata != METADATA_TYPES:
        gaps.append("missing_metadata_variants")
    return {"status": "CANDIDATE_REVIEW_REQUIRED" if not gaps else "NEEDS_REVISION",
            "human_review_complete": False,
            "question_count": len(questions), "pack_count": len(packs),
            "task_type_counts": dict(sorted(Counter(item.task_type for item in questions).items())),
            "pack_issues": pack_issues, "pack_scope_issues": sorted(scope_issues),
            "cross_pack_overlap": cross_pack_overlap, "boundary_examples": evidence,
            "missing_metadata_variants": sorted(metadata), "coverage_gaps": gaps,
            "questions_sha256": _digest(questions), "references_sha256": _digest(references)}
