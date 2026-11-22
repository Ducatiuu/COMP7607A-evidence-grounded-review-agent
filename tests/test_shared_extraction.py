import hashlib
import json
from pathlib import Path

import pytest

from eval.report import summarize_runs
from eval.run_method import main as run_method_main
from eval.shared_extraction import load_shared_extraction, prepare_mock_shared_extraction
from eval.questions import GoldReference
from scripts.prepare_shared_extraction import main as prepare_main
from scripts.summarize_runs import main as summarize_main
from src.data_loader import load_csv
from src.schemas import RecordSet


ROOT = Path(__file__).resolve().parents[1]


def test_shared_extraction_is_prepared_once_and_reused_by_b_and_c(tmp_path):
    shared = tmp_path / "shared"
    assert prepare_main(["--mock", "--out", str(shared)]) == 0
    records = load_csv(ROOT / "data/demo/core.csv")
    dataset, manifest_sha256, manifest = load_shared_extraction(records, shared)
    assert manifest.requests == len(records.records) == 4
    assert dataset.coverage.success == 4 and dataset.evidence_origin == "model_span"
    calls_path = shared / "model_calls.jsonl"
    initial_calls = calls_path.read_bytes()
    assert all(json.loads(line)["stage"] == "extract" for line in initial_calls.splitlines())
    assert prepare_mock_shared_extraction(records, shared)[1] == manifest_sha256
    assert calls_path.read_bytes() == initial_calls

    directories = []
    for method, expected_requests in [("b", 2), ("c", 4)]:
        directory = tmp_path / method
        args = ["--method", method, "--mock", "--shared-extraction", str(shared), "--out", str(directory)]
        assert run_method_main(args) == 0
        row = json.loads((directory / "answers.jsonl").read_text(encoding="utf-8"))
        run_manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        query_calls = (directory / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()
        assert row["status"] == "ok" and row["api_requests"] == expected_requests
        assert row["answer"]["usage"]["extraction_requests"] == 0
        assert "extraction_wall_latency_ms" not in row["answer"]["usage"]
        assert run_manifest["config"]["condition_artifact_sha256"] == manifest_sha256
        assert len(query_calls) == expected_requests
        assert all(json.loads(line)["stage"] != "extract" for line in query_calls)
        assert run_method_main(args) == 0
        assert len((directory / "answers.jsonl").read_text(encoding="utf-8").splitlines()) == 1
        directories.append(directory)

    refs = [GoldReference.model_validate(item) for item in json.loads(
        (ROOT / "data/demo/core_reference.json").read_text(encoding="utf-8"))]
    report = summarize_runs(directories, refs)
    assert report["paired"]["main"]["count"] == 1
    assert all(item["scores"]["equal_type_average"] == 1 for item in report["runs"])
    assert sum(item["api_requests_known"] for item in report["runs"]) + manifest.requests == 10
    combined = summarize_runs(directories, refs, shared_extraction_dir=shared)["shared_extraction"]
    assert combined["manifest_sha256"] == manifest_sha256
    assert combined["setup_physical_requests"] == 4
    assert combined["method_query_physical_requests"] == {"b": 2, "c": 4}
    assert combined["method_ledger_agreement"] == {"b": True, "c": True}
    assert combined["combined_physical_requests"] == 10 and combined["cost_usd"] is None
    target = tmp_path / "combined-report.json"
    assert summarize_main(["--runs", *(str(item) for item in directories), "--references",
                           str(ROOT / "data/demo/core_reference.json"), "--shared-extraction", str(shared),
                           "--out", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["shared_extraction"]["combined_physical_requests"] == 10

    other_shared = tmp_path / "other-shared"
    prepare_mock_shared_extraction(records, other_shared)
    with pytest.raises(ValueError, match="not bound to the shared extraction"):
        summarize_runs(directories, refs, shared_extraction_dir=other_shared)

    (directories[1] / "model_calls.jsonl").unlink()
    partial = summarize_runs(directories, refs, shared_extraction_dir=shared)["shared_extraction"]
    assert partial["method_query_physical_requests"] == {"b": 2, "c": None}
    assert partial["combined_physical_requests"] is None

    repeated = tmp_path / "repeated-c"
    assert run_method_main(["--method", "c", "--condition", "repeats", "--mock",
                            "--shared-extraction", str(shared), "--out", str(repeated)]) == 0
    repeat_rows = [json.loads(line) for line in (repeated / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    repeat_calls = [json.loads(line) for line in (repeated / "model_calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(repeat_rows) == 2 and len(repeat_calls) == 8
    assert all(row["api_requests"] == 4 for row in repeat_rows)
    assert all(call["stage"] != "extract" for call in repeat_calls)


def test_shared_extraction_rejects_changed_source_tampering_and_mixed_resume(tmp_path):
    records = load_csv(ROOT / "data/demo/core.csv")
    shared = tmp_path / "shared"
    prepare_mock_shared_extraction(records, shared)
    changed = RecordSet(records=[records.records[0].model_copy(update={"text": "Changed review"}),
                                 *records.records[1:]])
    with pytest.raises(ValueError, match="source records differ"):
        load_shared_extraction(changed, shared)
    for method, condition in [("a", "main"), ("b", "gold")]:
        with pytest.raises(SystemExit) as rejected:
            run_method_main(["--method", method, "--condition", condition, "--mock",
                             "--shared-extraction", str(shared), "--out", str(tmp_path / "rejected")])
        assert rejected.value.code == 2

    output = tmp_path / "b"
    assert run_method_main(["--method", "b", "--mock", "--shared-extraction", str(shared),
                            "--out", str(output)]) == 0
    with pytest.raises(ValueError, match="resume manifest/config/task list mismatch"):
        run_method_main(["--method", "b", "--mock", "--out", str(output)])

    calls_path = shared / "model_calls.jsonl"
    original_calls = calls_path.read_bytes()
    calls_path.write_bytes(original_calls + b"\n")
    with pytest.raises(ValueError, match="call ledger hash mismatch"):
        load_shared_extraction(records, shared)
    calls_path.write_bytes(original_calls)

    dataset_path = shared / "dataset.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset["provider_model"] = "gold-substitution"
    raw = json.dumps(dataset).encode("utf-8")
    dataset_path.write_bytes(raw)
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        load_shared_extraction(records, shared)
    manifest_path = shared / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="model provenance differs"):
        load_shared_extraction(records, shared)
