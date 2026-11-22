"""Separate contrastive extraction metrics; label provenance is explicit."""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import Field, model_validator

from src.schemas import Category, ExtractionResult, Sentiment
from src.schemas.models import StrictModel
from src.semeval import GoldRecord


class ChallengeReference(StrictModel):
    pair_id: str = Field(min_length=1)
    source_gold: GoldRecord
    edited_gold: GoldRecord
    intended_change_categories: list[Category]
    stable_categories: list[Category]
    subgroup_tags: list[Literal["negation", "contrast", "implicit_aspect", "within_aspect_conflict"]]
    provenance: Literal["SYNTHETIC_TEST_ONLY", "HUMAN_ADJUDICATED"]
    independent_reviewer_ids: list[str] = Field(default_factory=list)
    adjudicator_id: str | None = None
    annotation_record_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def coherent(self) -> "ChallengeReference":
        if self.source_gold.record_id == self.edited_gold.record_id:
            raise ValueError("source and edited IDs must differ")
        if not self.intended_change_categories or len(set(self.intended_change_categories)) != len(self.intended_change_categories):
            raise ValueError("at least one unique intended change is required")
        if len(set(self.stable_categories)) != len(self.stable_categories) or set(self.intended_change_categories) & set(self.stable_categories):
            raise ValueError("stable and changed categories must be distinct")
        if not self.subgroup_tags or len(set(self.subgroup_tags)) != len(self.subgroup_tags):
            raise ValueError("one or more unique subgroup tags required")
        before = {item.category: item.sentiment for item in self.source_gold.aspects}
        after = {item.category: item.sentiment for item in self.edited_gold.aspects}
        if any(before.get(category) == after.get(category) for category in self.intended_change_categories):
            raise ValueError("intended change category does not change in reference")
        if any(before.get(category) != after.get(category) or category not in before for category in self.stable_categories):
            raise ValueError("stable category must occur unchanged in both records")
        if self.provenance == "HUMAN_ADJUDICATED":
            reviewers = self.independent_reviewer_ids
            if (len(reviewers) != 2 or len(set(reviewers)) != 2 or not self.adjudicator_id
                    or self.adjudicator_id in reviewers or not self.annotation_record_sha256):
                raise ValueError("human references require two independent reviewers, a distinct adjudicator and source hash")
        elif self.independent_reviewer_ids or self.adjudicator_id or self.annotation_record_sha256:
            raise ValueError("synthetic test reference cannot claim human review metadata")
        return self


class ChallengePrediction(StrictModel):
    pair_id: str = Field(min_length=1)
    source: ExtractionResult
    edited: ExtractionResult
    mode: Literal["MOCK", "LIVE"]

    @model_validator(mode="after")
    def distinct(self) -> "ChallengePrediction":
        if self.source.record_id == self.edited.record_id:
            raise ValueError("prediction source and edited IDs must differ")
        return self


def prediction_from_run_payload(payload: dict) -> ChallengePrediction:
    if payload.get("condition") != "challenge" or not isinstance(payload.get("predictions"), list) or len(payload["predictions"]) != 2:
        raise ValueError("expected exactly one challenge pair's extraction payload")
    return ChallengePrediction(pair_id=payload["pair_id"], source=payload["predictions"][0],
                               edited=payload["predictions"][1], mode=payload["mode"])


def _labels(result: ExtractionResult) -> dict[Category, Sentiment]:
    return {item.category: item.sentiment for item in result.aspects} if result.status == "ok" else {}


def score_challenge_predictions(predictions: list[ChallengePrediction], references: list[ChallengeReference]) -> dict:
    if not predictions or not references:
        raise ValueError("nonempty predictions and adjudicated or synthetic references required")
    by_prediction = {item.pair_id: item for item in predictions}
    by_reference = {item.pair_id: item for item in references}
    if (len(by_prediction) != len(predictions) or len(by_reference) != len(references)
            or set(by_prediction) != set(by_reference)):
        raise ValueError("challenge pair IDs must align uniquely")
    provenances = {item.provenance for item in references}
    if len(provenances) != 1:
        raise ValueError("cannot mix synthetic and human reference provenance")
    provenance = provenances.pop()
    if provenance == "HUMAN_ADJUDICATED" and any(item.mode != "LIVE" for item in predictions):
        raise ValueError("MOCK predictions cannot be reported as human-adjudicated live results")
    changed_total = changed_correct = stable_total = stable_correct = pair_correct = failures = 0
    by_subgroup: dict[str, list[bool]] = defaultdict(list)
    for pair_id, reference in by_reference.items():
        prediction = by_prediction[pair_id]
        if (prediction.source.record_id != reference.source_gold.record_id
                or prediction.edited.record_id != reference.edited_gold.record_id):
            raise ValueError("challenge record IDs do not match reference")
        complete = prediction.source.status == prediction.edited.status == "ok"
        failures += not complete
        expected_source = {item.category: item.sentiment for item in reference.source_gold.aspects}
        expected_edited = {item.category: item.sentiment for item in reference.edited_gold.aspects}
        predicted_source = _labels(prediction.source)
        predicted_edited = _labels(prediction.edited)
        changed = [complete and predicted_source.get(category) == expected_source.get(category)
                   and predicted_edited.get(category) == expected_edited.get(category)
                   for category in reference.intended_change_categories]
        stable = [complete and predicted_source.get(category) == expected_source.get(category)
                  and predicted_edited.get(category) == expected_edited.get(category)
                  for category in reference.stable_categories]
        changed_total += len(changed)
        changed_correct += sum(changed)
        stable_total += len(stable)
        stable_correct += sum(stable)
        passed = complete and all(changed) and all(stable)
        pair_correct += passed
        for subgroup in reference.subgroup_tags:
            by_subgroup[subgroup].append(passed)
    return {"provenance": provenance, "pair_count": len(references),
            "failed_extraction_pairs": failures,
            "intended_change": {"correct": changed_correct, "total": changed_total,
                                "accuracy": changed_correct / changed_total},
            "stable_aspects": {"correct": stable_correct, "total": stable_total,
                               "accuracy": stable_correct / stable_total if stable_total else None},
            "pair_accuracy": pair_correct / len(references),
            "by_subgroup": {name: {"support_pairs": len(values), "pair_accuracy": sum(values) / len(values)}
                            for name, values in sorted(by_subgroup.items())}}
