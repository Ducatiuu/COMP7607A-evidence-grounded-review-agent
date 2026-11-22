"""One reusable, hash-bound MOCK extraction artifact for offline B/C comparisons."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.data_loader import dataset_fingerprint
from src.schemas import ExtractionDataset, RecordSet
from src.schemas.models import StrictModel

from .efficiency import ModelCallRow


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _config_hash(dataset_sha256: str) -> str:
    config = {"dataset_sha256": dataset_sha256, "provider_model": "mock",
              "prompt_version": "extract-v1", "schema_version": "v1"}
    return _sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class SharedExtractionManifest(StrictModel):
    mode: Literal["MOCK"] = "MOCK"
    dataset_sha256: str = Field(min_length=64, max_length=64)
    config_sha256: str = Field(min_length=64, max_length=64)
    artifact_sha256: str = Field(min_length=64, max_length=64)
    calls_sha256: str = Field(min_length=64, max_length=64)
    provider_model: Literal["mock"] = "mock"
    prompt_version: Literal["extract-v1"] = "extract-v1"
    schema_version: Literal["v1"] = "v1"
    requests: int = Field(ge=1)
    retries: int = Field(ge=0)
    cache_hits: int = Field(ge=0)
    extraction_wall_latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def aligned(self) -> "SharedExtractionManifest":
        if self.config_sha256 != _config_hash(self.dataset_sha256):
            raise ValueError("shared extraction config hash mismatch")
        return self


def load_shared_extraction(records: RecordSet, directory: str | Path) -> tuple[ExtractionDataset, str, SharedExtractionManifest]:
    """Validate source, model provenance, artifact bytes and all physical extraction calls."""
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    dataset_path = directory / "dataset.json"
    calls_path = directory / "model_calls.jsonl"
    if not all(path.is_file() for path in (manifest_path, dataset_path, calls_path)):
        raise ValueError("shared extraction artifact is incomplete")
    manifest_bytes = manifest_path.read_bytes()
    manifest = SharedExtractionManifest.model_validate_json(manifest_bytes)
    dataset_bytes = dataset_path.read_bytes()
    if manifest.artifact_sha256 != _sha256(dataset_bytes):
        raise ValueError("shared extraction artifact hash mismatch")
    calls_bytes = calls_path.read_bytes()
    if manifest.calls_sha256 != _sha256(calls_bytes):
        raise ValueError("shared extraction call ledger hash mismatch")
    dataset = ExtractionDataset.model_validate_json(dataset_bytes)
    if (manifest.dataset_sha256 != dataset_fingerprint(records) or dataset.fingerprint != manifest.dataset_sha256
            or dataset.records != records.records):
        raise ValueError("shared extraction source records differ")
    if (dataset.provider_model != manifest.provider_model or dataset.prompt_version != manifest.prompt_version
            or dataset.schema_version != manifest.schema_version or dataset.evidence_origin != "model_span"):
        raise ValueError("shared extraction model provenance differs")
    calls = [ModelCallRow.model_validate_json(line) for line in calls_bytes.decode("utf-8").splitlines()]
    record_ids = {record.record_id for record in records.records}
    called_ids = {call.record_id for call in calls}
    if (len(calls) != manifest.requests or len({call.run_id for call in calls}) != 1
            or any(call.stage != "extract" or call.config_sha256 != manifest.config_sha256
                   or call.record_id not in record_ids
                   or call.call_index != index for index, call in enumerate(calls, start=1))
            or len(record_ids - called_ids) != manifest.cache_hits
            or len(calls) - len(called_ids) != manifest.retries):
        raise ValueError("shared extraction call ledger differs")
    return dataset, _sha256(manifest_bytes), manifest


def prepare_mock_shared_extraction(records: RecordSet, directory: str | Path) -> tuple[ExtractionDataset, str, SharedExtractionManifest]:
    """Run extraction once; matching reruns verify and reuse the existing artifact."""
    from src.absa_service import ExtractionService
    from src.demo_mock import mock_for_demo
    from src.llm_telemetry import RecordingLLMClient

    directory = Path(directory)
    filenames = ("manifest.json", "dataset.json", "model_calls.jsonl")
    if any((directory / name).exists() for name in filenames):
        return load_shared_extraction(records, directory)
    directory.mkdir(parents=True, exist_ok=True)
    source_hash = dataset_fingerprint(records)
    config_hash = _config_hash(source_hash)
    client = RecordingLLMClient(
        delegate=mock_for_demo(records, method="extract"), output_path=directory / "model_calls.jsonl",
        run_id=str(uuid.uuid4()), configured_model="mock", config_sha256=config_hash, record_content=True,
    )
    started = time.perf_counter()
    run = ExtractionService(client, provider_model="mock").extract(records)
    duration_ms = (time.perf_counter() - started) * 1000
    dataset_bytes = run.dataset.model_dump_json(indent=2).encode("utf-8")
    calls_sha256 = _sha256((directory / "model_calls.jsonl").read_bytes())
    manifest = SharedExtractionManifest(
        dataset_sha256=source_hash, config_sha256=config_hash, artifact_sha256=_sha256(dataset_bytes),
        calls_sha256=calls_sha256,
        requests=run.requests, retries=run.retries, cache_hits=run.cache_hits,
        extraction_wall_latency_ms=duration_ms,
    )
    temporary_dataset = directory / "dataset.json.tmp"
    temporary_manifest = directory / "manifest.json.tmp"
    temporary_dataset.write_bytes(dataset_bytes)
    temporary_dataset.replace(directory / "dataset.json")
    temporary_manifest.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    temporary_manifest.replace(directory / "manifest.json")
    return load_shared_extraction(records, directory)
