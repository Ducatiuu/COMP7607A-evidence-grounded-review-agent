"""Pre-result deterministic candidate subsets; no gold or model outputs are used."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Literal

from pydantic import Field, model_validator

from src.schemas.models import StrictModel
from .questions import QuestionCandidate


class CandidateSubsets(StrictModel):
    status: Literal["CANDIDATE_UNREVIEWED"] = "CANDIDATE_UNREVIEWED"
    source_questions_sha256: str = Field(min_length=64, max_length=64)
    repeats: list[str]
    gold_diagnostic: list[str]
    verification_ablation: list[str]
    evidence_review: list[str]
    manifest_sha256: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def valid(self) -> "CandidateSubsets":
        if any(len(items) != len(set(items)) for items in
               [self.repeats, self.gold_diagnostic, self.verification_ablation, self.evidence_review]):
            raise ValueError("duplicate subset question ID")
        material = self.model_dump(exclude={"manifest_sha256"})
        if self.manifest_sha256 != _digest(material):
            raise ValueError("subset manifest hash mismatch")
        return self


def _digest(material: object) -> str:
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_candidate_subsets(questions: list[QuestionCandidate]) -> CandidateSubsets:
    by_pack: dict[str, list[QuestionCandidate]] = defaultdict(list)
    ids = set()
    for question in questions:
        if question.question_id in ids:
            raise ValueError("duplicate question ID")
        ids.add(question.question_id)
        by_pack[question.pack_id].append(question)
    if len(by_pack) != 20 or any(len(items) != 6 or len({item.task_type for item in items}) != 6
                                   for items in by_pack.values()):
        raise ValueError("candidate subsets require 20 complete six-type packs")
    packs = [sorted(items, key=lambda item: item.question_id) for _, items in sorted(by_pack.items())]
    repeats = [pack[index % 6].question_id for index, pack in enumerate(packs)]
    diagnostic = [pack[(index + 1) % 6].question_id for index, pack in enumerate(packs)]
    diagnostic += [packs[index][(index + 3) % 6].question_id for index in range(10)]
    evidence = [pack[(index + 4) % 6].question_id for index, pack in enumerate(packs)]
    evidence += [packs[index][(index + 2) % 6].question_id for index in range(10)]
    material = {
        "status": "CANDIDATE_UNREVIEWED", "source_questions_sha256": _digest([item.model_dump(mode="json") for item in questions]),
        "repeats": repeats, "gold_diagnostic": diagnostic,
        "verification_ablation": diagnostic, "evidence_review": evidence,
    }
    return CandidateSubsets(**material, manifest_sha256=_digest(material))
