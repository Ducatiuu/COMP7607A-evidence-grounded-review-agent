import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUESTION = "What is the negative service rate?"


def _run(*args):
    return subprocess.run([sys.executable, "-m", "src.cli", *args], cwd=ROOT, text=True, capture_output=True)


def test_cli_extract_and_a_b_use_explicit_mock_label():
    extracted = _run("extract", "--input", "data/demo/core.csv", "--mock")
    assert extracted.returncode == 0, extracted.stderr
    data = json.loads(extracted.stdout)
    assert data["mode"] == "MOCK" and data["dataset"]["coverage"] == {"total": 4, "success": 4, "failed_ids": []}
    answers = {}
    for method in ("a", "b"):
        completed = _run("ask", "--method", method, "--input", "data/demo/core.csv", "--question", QUESTION, "--mock")
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["mode"] == "MOCK"
        answers[method] = payload["answer"]
        assert answers[method]["status"] == "ok" and answers[method]["method"] == method
        assert answers[method]["numeric_claims"][0]["value"] == 2 / 3
    assert answers["a"]["tool_trace"] == []
    assert [event["tool_name"] for event in answers["b"]["tool_trace"]] == ["aggregate_aspects"]


def test_cli_rejects_unknown_mock_question_and_pending_c():
    unknown = _run("ask", "--method", "b", "--input", "data/demo/core.csv", "--question", "Another question", "--mock")
    assert unknown.returncode != 0 and "only supports this exact question" in unknown.stderr
    pending = _run("ask", "--method", "c", "--input", "data/demo/core.csv", "--question", QUESTION, "--mock")
    assert pending.returncode != 0 and "pending Phase 4" in pending.stderr
