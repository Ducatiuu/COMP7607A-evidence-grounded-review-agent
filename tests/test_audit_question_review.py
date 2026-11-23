import csv
import json

import pytest

from eval.questions import GoldReference, QuestionCandidate
from scripts.audit_question_review import _JUDGMENTS, audit_review_sheets, main
from scripts.export_question_review import _FIELDS


def _candidate():
    question = QuestionCandidate(question_id="P01-Q1", pack_id="P01", record_ids=["R1"],
                                 task_type="count", wording="How many negative service reviews?",
                                 expected_fields=["count"])
    reference = GoldReference(question_id="P01-Q1", task_type="count", count=1)
    return question, reference


def _row(question, reference, *, reviewer_id="", judgment=""):
    row = dict.fromkeys(_FIELDS, "")
    row.update(question_id=question.question_id, pack_id=question.pack_id,
               task_type=question.task_type, wording=question.wording,
               record_ids=json.dumps(question.record_ids),
               expected_fields=json.dumps(question.expected_fields),
               reference_json=reference.model_dump_json(),
               questions_sha256="a" * 64, references_sha256="b" * 64,
               reviewer_id=reviewer_id)
    for field in _JUDGMENTS:
        row[field] = judgment
    return row


def _write_sheet(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_FIELDS)
        writer.writeheader()
        writer.writerows(row if isinstance(row, list) else [row])


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.audit_question_review.audit_candidate_questions",
                        lambda *_: {"coverage_gaps": [], "questions_sha256": "a" * 64,
                                    "references_sha256": "b" * 64})
    question, reference = _candidate()
    directory = tmp_path / ("a" * 12)
    sheet_1, sheet_2 = directory / "reviewer_1.csv", directory / "reviewer_2.csv"
    return question, reference, sheet_1, sheet_2


def test_blank_then_complete_review_remains_unfrozen(tmp_path, monkeypatch, capsys):
    question, reference, sheet_1, sheet_2 = _setup(tmp_path, monkeypatch)
    _write_sheet(sheet_1, _row(question, reference))
    _write_sheet(sheet_2, _row(question, reference))
    result = audit_review_sheets([question], [reference], sheet_1, sheet_2)
    assert result["status"] == "PENDING_HUMAN_REVIEW" and result["missing_judgments"] == 8
    assert not result["human_review_verified"] and not result["frozen"]
    question_path, reference_path = tmp_path / "questions.json", tmp_path / "refs.json"
    question_path.write_text(json.dumps([question.model_dump(mode="json")]), encoding="utf-8")
    reference_path.write_text(json.dumps([reference.model_dump(mode="json")]), encoding="utf-8")
    args = ["--questions", str(question_path), "--references", str(reference_path),
            "--sheets-root", str(tmp_path)]
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "PENDING_HUMAN_REVIEW"
    _write_sheet(sheet_1, _row(question, reference, reviewer_id="reviewer-a", judgment="yes"))
    _write_sheet(sheet_2, _row(question, reference, reviewer_id="reviewer-b", judgment="yes"))
    assert main(args) == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported["status"] == "REPORTED_READY_FOR_MAINTAINER_REVIEW"
    assert reported["missing_judgments"] == 0 and not reported["frozen"]


def test_disagreement_and_rejection_require_human_adjudication(tmp_path, monkeypatch):
    question, reference, sheet_1, sheet_2 = _setup(tmp_path, monkeypatch)
    row_1 = _row(question, reference, reviewer_id="reviewer-a", judgment="yes")
    row_2 = _row(question, reference, reviewer_id="reviewer-b", judgment="yes")
    row_2["reference_ok"] = "no"
    row_2["proposed_edit"] = "Check reference"
    _write_sheet(sheet_1, row_1)
    _write_sheet(sheet_2, row_2)
    result = audit_review_sheets([question], [reference], sheet_1, sheet_2)
    assert result["status"] == "NEEDS_HUMAN_ADJUDICATION"
    assert (result["rejected_judgments"], result["disagreements"], result["proposed_edits"]) == (1, 1, 1)


def test_tampering_or_same_reviewer_is_rejected(tmp_path, monkeypatch):
    question, reference, sheet_1, sheet_2 = _setup(tmp_path, monkeypatch)
    row_1 = _row(question, reference, reviewer_id="reviewer-a", judgment="yes")
    row_2 = _row(question, reference, reviewer_id="reviewer-a", judgment="yes")
    _write_sheet(sheet_1, row_1)
    _write_sheet(sheet_2, row_2)
    with pytest.raises(ValueError, match="distinct reviewer"):
        audit_review_sheets([question], [reference], sheet_1, sheet_2)
    row_2["reviewer_id"] = "reviewer-b"
    row_2["reference_json"] = json.dumps({"count": 999})
    _write_sheet(sheet_2, row_2)
    with pytest.raises(ValueError, match="independent reference"):
        audit_review_sheets([question], [reference], sheet_1, sheet_2)
    row_2 = _row(question, reference, reviewer_id="reviewer-b", judgment="yes")
    row_2["questions_sha256"] = "f" * 64
    _write_sheet(sheet_2, row_2)
    with pytest.raises(ValueError, match="immutable"):
        audit_review_sheets([question], [reference], sheet_1, sheet_2)


def test_missing_reviewer_id_on_any_row_prevents_ready_status(tmp_path, monkeypatch):
    question, reference, sheet_1, sheet_2 = _setup(tmp_path, monkeypatch)
    second = question.model_copy(update={"question_id": "P01-Q2"})
    second_reference = reference.model_copy(update={"question_id": "P01-Q2"})
    _write_sheet(sheet_1, [_row(question, reference, reviewer_id="reviewer-a", judgment="yes"),
                           _row(second, second_reference, judgment="yes")])
    _write_sheet(sheet_2, [_row(question, reference, reviewer_id="reviewer-b", judgment="yes"),
                           _row(second, second_reference, reviewer_id="reviewer-b", judgment="yes")])
    result = audit_review_sheets([question, second], [reference, second_reference], sheet_1, sheet_2)
    assert result["status"] == "PENDING_HUMAN_REVIEW"
    assert result["missing_judgments"] == 0 and result["missing_reviewer_ids"] == 1
