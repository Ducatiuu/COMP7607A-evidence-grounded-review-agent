"""Diagnostic-only condition artifacts, isolated from normal runtime paths."""

from __future__ import annotations

from src.data_loader import dataset_fingerprint
from src.schemas import Coverage, ExtractionDataset, ExtractionResult, RecordSet
from src.semeval import GoldRecord


def gold_substitution_dataset(records: RecordSet, gold: list[GoldRecord], *, source_sha256: str) -> ExtractionDataset:
    """Use labels for an explicit diagnostic; full sentence is not a rationale span."""
    gold_by_id = {item.record_id: item for item in gold}
    if len(gold_by_id) != len(gold) or set(gold_by_id) != {record.record_id for record in records.records}:
        raise ValueError("gold substitution IDs must match raw records exactly")
    results = []
    for record in records.records:
        aspects = [{"category": label.category, "sentiment": label.sentiment, "evidence": [record.text]}
                   for label in gold_by_id[record.record_id].aspects]
        results.append(ExtractionResult(record_id=record.record_id, aspects=aspects, status="ok"))
    return ExtractionDataset(
        fingerprint=dataset_fingerprint(records), records=records.records, extractions=results,
        provider_model="gold-substitution", prompt_version=f"gold-source-{source_sha256}", schema_version="v1",
        evidence_origin="full_sentence_unannotated",
        coverage=Coverage(total=len(records.records), success=len(records.records)),
    )
