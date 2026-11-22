"""Challenge candidates and extraction-only MOCK dry-run; no human labels or scores."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.absa_service import ExtractionService
from src.llm_client import LLMResponse, MockLLMClient
from src.schemas import Record, RecordSet
from src.schemas.models import StrictModel


class ChallengeCandidate(StrictModel):
    status: Literal["CANDIDATE_UNREVIEWED"] = "CANDIDATE_UNREVIEWED"
    pair_id: str = Field(min_length=1)
    source: Record
    edited: Record
    candidate_edit_description: str = Field(min_length=1)

    @model_validator(mode="after")
    def distinct(self) -> "ChallengeCandidate":
        if self.source.record_id == self.edited.record_id or self.source.text == self.edited.text:
            raise ValueError("challenge pair must have distinct IDs and text")
        return self


_MOCK_ASPECTS = {
    "CH01-A": [("food", "positive", "food was excellent"), ("service", "negative", "service was slow")],
    "CH01-B": [("food", "positive", "food was excellent"), ("service", "positive", "service was attentive")],
}
_MOCK_TEXT = {
    "CH01-A": "The food was excellent, but service was slow.",
    "CH01-B": "The food was excellent, and service was attentive.",
}


def run_synthetic_challenge(candidate_path: str | Path, output_dir: str | Path) -> dict:
    source_path = Path(candidate_path)
    raw = source_path.read_bytes()
    candidate = ChallengeCandidate.model_validate_json(raw)
    if candidate.pair_id != "synthetic-pair-01" or [candidate.source.record_id, candidate.edited.record_id] != ["CH01-A", "CH01-B"]:
        raise ValueError("MOCK challenge only supports its named synthetic pair")
    records = RecordSet(records=[candidate.source, candidate.edited])
    for record in records.records:
        if record.text != _MOCK_TEXT[record.record_id]:
            raise ValueError("MOCK challenge sentence differs from canned extraction fixture")
    digest = hashlib.sha256(raw).hexdigest()
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    predictions_path = directory / "predictions.json"
    manifest = {"mode": "MOCK", "condition": "challenge", "source_sha256": digest,
                "pair_id": candidate.pair_id, "status": "CANDIDATE_UNREVIEWED"}
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise ValueError("challenge resume manifest mismatch")
        if predictions_path.exists():
            previous = json.loads(predictions_path.read_text(encoding="utf-8"))
            if (previous.get("mode") != "MOCK" or previous.get("pair_id") != candidate.pair_id
                    or [item.get("record_id") for item in previous.get("predictions", [])] != ["CH01-A", "CH01-B"]):
                raise ValueError("challenge predictions do not match manifest")
            return {"mode": "MOCK", "recorded": 0, "skipped_existing": 1, "scores": None}
    elif predictions_path.exists():
        raise ValueError("predictions exist without challenge manifest")
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    responses = deque(LLMResponse(model="mock", content={
        "record_id": record.record_id,
        "aspects": [{"category": category, "sentiment": sentiment, "evidence": [quote]}
                    for category, sentiment, quote in _MOCK_ASPECTS[record.record_id]],
        "status": "ok", "error": None,
    }) for record in records.records)
    extraction = ExtractionService(MockLLMClient(responses), provider_model="mock").extract(records)
    payload = {"mode": "MOCK", "condition": "challenge", "pair_id": candidate.pair_id,
               "status": "CANDIDATE_UNREVIEWED", "api_requests": extraction.requests,
               "predictions": [item.model_dump(mode="json") for item in extraction.dataset.extractions],
               "scores": None, "human_labels": None}
    predictions_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"mode": "MOCK", "recorded": 1, "skipped_existing": 0, "scores": None}
