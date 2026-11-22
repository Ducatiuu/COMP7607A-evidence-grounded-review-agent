import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from eval.conditions import gold_substitution_dataset
from eval.run_method import main as run_method_main
from eval.runner import RunConfig
from src.data_loader import load_csv
from src.demo_mock import DEMO_QUESTION, run_demo_method
from src.semeval import GoldRecord


ROOT = Path(__file__).resolve().parents[1]


def test_gold_substitution_has_full_sentence_only_and_explicit_origin():
    records = load_csv(ROOT / "data/demo/core.csv")
    path = ROOT / "data/demo/core_gold.json"
    gold = [GoldRecord.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]
    artifact = gold_substitution_dataset(records, gold, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert artifact.evidence_origin == "full_sentence_unannotated"
    assert artifact.extractions[0].aspects[0].evidence == [records.records[0].text]
    answer, extraction_requests = run_demo_method(records, method="b", question=DEMO_QUESTION, extraction_dataset=artifact)
    assert answer.status == "ok" and extraction_requests == 0 and answer.numeric_claims[0].value == 2 / 3
    with pytest.raises(ValueError, match="IDs must match"):
        gold_substitution_dataset(records, gold[:-1], source_sha256="a" * 64)


def test_gold_config_requires_artifact_hash():
    base = {"method": "b", "split": "demo", "condition": "gold", "dataset_sha256": "a" * 64,
            "question_manifest_sha256": "b" * 64, "model_id": "mock", "prompt_version": "v1"}
    with pytest.raises(ValidationError, match="hashed source artifact"):
        RunConfig(**base)
    assert RunConfig(**base, condition_artifact_sha256="c" * 64).condition == "gold"


@pytest.mark.parametrize("condition,method,requests", [("gold", "b", 2), ("gold", "c", 4), ("ablation", "c", 8)])
def test_condition_cli_is_mock_and_resumable(tmp_path, condition, method, requests):
    output = tmp_path / condition
    args = ["--method", method, "--condition", condition, "--mock", "--out", str(output)]
    assert run_method_main(args) == 0
    row = json.loads((output / "answers.jsonl").read_text(encoding="utf-8"))
    assert row["mode"] == "MOCK" and row["status"] == "ok" and row["api_requests"] == requests
    assert row["answer"]["numeric_claims"][0]["value"] == 2 / 3
    assert run_method_main(args) == 0
    assert len((output / "answers.jsonl").read_text(encoding="utf-8").splitlines()) == 1
