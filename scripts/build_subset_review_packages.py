"""Build local R1/R2 packets for 13 extraction rows and four fixed question packs."""

from __future__ import annotations

import argparse
import csv
import json
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

from eval.question_audit import audit_candidate_questions
from eval.questions import GoldReference, QuestionCandidate
from scripts.audit_question_review import audit_review_sheets
from scripts.build_human_review_packages import (
    EXTRACTION_EDITABLE, QUESTION_EDITABLE, _csv, _embedded_json, _sha, _zip_write,
)
from src.semeval import GoldRecord


# Fixed before any formal model run: pack positions 1, 6, 11 and 16 of P01..P20.
SELECTED_PACKS = ("P01", "P06", "P11", "P16")
SELECTION_RULE = "P01..P20 in numeric order; choose positions 1, 6, 11, 16 (stride 5)"


def _csv_bytes(fields: list[str], rows: list[dict[str, str]]) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def build_subset_packets(*, extraction_root: Path, question_root: Path, test_csv: Path,
                         test_gold: Path, candidate_questions: Path, candidate_references: Path,
                         annotation_guide: Path, guide_template: Path, page_template: Path,
                         out: Path) -> list[Path]:
    if out.exists():
        raise FileExistsError(f"output directory already exists: {out}")
    full_bytes = {"questions": candidate_questions.read_bytes(),
                  "references": candidate_references.read_bytes()}
    full_q = [QuestionCandidate.model_validate(x) for x in json.loads(full_bytes["questions"])]
    full_r = [GoldReference.model_validate(x) for x in json.loads(full_bytes["references"])]
    full_audit = audit_candidate_questions(full_q, full_r)
    if full_audit["coverage_gaps"] or len(full_q) != 120:
        raise ValueError("the 120-question source is incomplete")
    original_audit = audit_review_sheets(full_q, full_r, question_root / "reviewer_1.csv",
                                         question_root / "reviewer_2.csv")
    if (original_audit["status"] != "PENDING_HUMAN_REVIEW"
            or original_audit["missing_judgments"] != 960
            or original_audit["missing_reviewer_ids"] != 240):
        raise ValueError("the 120-question source sheets are no longer blank")
    if tuple(sorted({q.pack_id for q in full_q})) != tuple(f"P{i:02d}" for i in range(1, 21)):
        raise ValueError("unexpected source Pack IDs")
    selected_q = [q for q in full_q if q.pack_id in SELECTED_PACKS]
    selected_ids = {q.question_id for q in selected_q}
    selected_r = [r for r in full_r if r.question_id in selected_ids]
    subset_audit = audit_candidate_questions(selected_q, selected_r, expected_packs=4)
    if len(selected_q) != 24 or subset_audit["coverage_gaps"]:
        raise ValueError("selected packs fail the four-pack coverage audit")
    record_ids = {rid for q in selected_q for rid in q.record_ids}
    source_test_bytes = test_csv.read_bytes()
    source_gold_bytes = test_gold.read_bytes()
    test_fields, full_test_rows = _csv(source_test_bytes)
    full_gold = [GoldRecord.model_validate(x) for x in json.loads(source_gold_bytes)]
    if (len(full_test_rows) != 600 or len(full_gold) != 600
            or [r["record_id"] for r in full_test_rows] != [r.record_id for r in full_gold]
            or len(record_ids) != 120):
        raise ValueError("formal source records or selected Pack scopes are invalid")
    subset_test = [r for r in full_test_rows if r["record_id"] in record_ids]
    subset_gold = [r.model_dump(mode="json") for r in full_gold if r.record_id in record_ids]
    if len(subset_test) != 120 or len(subset_gold) != 120:
        raise ValueError("the selected Pack record IDs do not match the formal source")
    source_files = {
        "test.csv": _csv_bytes(test_fields, subset_test),
        "test_gold.json": json.dumps(subset_gold, ensure_ascii=False, indent=2).encode("utf-8"),
        "candidate_questions.json": json.dumps([q.model_dump(mode="json") for q in selected_q],
                                               ensure_ascii=False, indent=2).encode("utf-8"),
        "candidate_references.json": json.dumps([r.model_dump(mode="json") for r in selected_r],
                                                ensure_ascii=False, indent=2).encode("utf-8"),
        "annotation_guide.md": annotation_guide.read_bytes(),
    }
    page_text = page_template.read_text(encoding="utf-8")
    guide_text = guide_template.read_text(encoding="utf-8")
    if (page_text.count("__REVIEW_DATA__") != 1
            or page_text.count("正式候选题（120）") != 1 or "__SLOT__" not in guide_text):
        raise ValueError("review templates are missing expected markers")
    page_text = page_text.replace("正式候选题（120）", "正式候选题（24）")
    pending = []
    first_extraction = first_questions = None
    for slot in (1, 2):
        extraction_bytes = (extraction_root / f"reviewer_{slot}.csv").read_bytes()
        ex_fields, ex_rows = _csv(extraction_bytes)
        if (len(ex_rows) != 13 or len({r["record_id"] for r in ex_rows}) != 13
                or any(any(r[field].strip() for field in EXTRACTION_EDITABLE) for r in ex_rows)):
            raise ValueError("extraction sheet is not the untouched 13-row source")
        ex_readonly = [{k: v for k, v in r.items() if k not in EXTRACTION_EDITABLE}
                       for r in ex_rows]
        if first_extraction is None:
            first_extraction = ex_readonly
        elif first_extraction != ex_readonly:
            raise ValueError("R1/R2 extraction sources differ")
        qu_fields, full_rows = _csv((question_root / f"reviewer_{slot}.csv").read_bytes())
        qu_rows = [dict(r) for r in full_rows if r["pack_id"] in SELECTED_PACKS]
        if len(qu_rows) != 24 or len({r["question_id"] for r in qu_rows}) != 24:
            raise ValueError("question sheet selection is incomplete")
        for row in qu_rows:
            row["questions_sha256"] = subset_audit["questions_sha256"]
            row["references_sha256"] = subset_audit["references_sha256"]
            if any(row[field].strip() for field in QUESTION_EDITABLE):
                raise ValueError("selected question sheet has human work")
        qu_readonly = [{k: v for k, v in r.items() if k not in QUESTION_EDITABLE}
                       for r in qu_rows]
        if first_questions is None:
            first_questions = qu_readonly
        elif first_questions != qu_readonly:
            raise ValueError("R1/R2 question sources differ")
        question_bytes = _csv_bytes(qu_fields, qu_rows)
        data = {
            "slot": slot, "extraction": ex_rows, "questions": qu_rows,
            "extractionFields": ex_fields, "questionFields": qu_fields,
            "testRecords": subset_test, "goldRecords": subset_gold,
            "sourceHashes": {name: _sha(content) for name, content in source_files.items()},
            "sheetHashes": {"extraction": _sha(extraction_bytes), "questions": _sha(question_bytes)},
        }
        files = {
            "START_HERE_ZH.md": guide_text.replace("__SLOT__", str(slot)).encode("utf-8"),
            "review.html": page_text.replace("__REVIEW_DATA__", _embedded_json(data)).encode("utf-8"),
            f"01_extraction/reviewer_{slot}.csv": extraction_bytes,
            f"02_questions/reviewer_{slot}.csv": question_bytes,
            **{f"readonly/{name}": content for name, content in source_files.items()},
        }
        manifest = {
            "status": "PENDING_INDEPENDENT_HUMAN_REVIEW", "reviewer_slot": slot,
            "selection_rule": SELECTION_RULE, "selected_pack_ids": SELECTED_PACKS,
            "extraction_rows": 13, "question_rows": 24, "test_record_rows": 120,
            "human_judgments_filled": False, "formal_predictions_included": False,
            "full_source_questions_sha256": full_audit["questions_sha256"],
            "full_source_references_sha256": full_audit["references_sha256"],
            "subset_questions_sha256": subset_audit["questions_sha256"],
            "subset_references_sha256": subset_audit["references_sha256"],
            "full_source_file_sha256": {
                "test.csv": _sha(source_test_bytes), "test_gold.json": _sha(source_gold_bytes),
                "candidate_questions.json": _sha(full_bytes["questions"]),
                "candidate_references.json": _sha(full_bytes["references"]),
            },
            "files_sha256": {name: _sha(content) for name, content in sorted(files.items())},
        }
        files["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        pending.append((out / f"reviewer_{slot}_13_plus_24.zip", files))
    out.mkdir(parents=True)
    for target, files in pending:
        with ZipFile(target, "x") as archive:
            for name, content in sorted(files.items()):
                _zip_write(archive, name, content)
    return [target for target, _ in pending]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 13+24 local human review packets")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    paths = build_subset_packets(
        extraction_root=Path("outputs/extraction_review_v8_2026-11-24"),
        question_root=Path("data/gold/question_review/0ba746858bfd"),
        test_csv=Path("data/processed/test.csv"), test_gold=Path("data/gold/test.json"),
        candidate_questions=Path("data/processed/candidate_questions.json"),
        candidate_references=Path("data/gold/candidate_references.json"),
        annotation_guide=Path("docs/annotation_guide.md"),
        guide_template=Path("docs/subset_review_packet_guide_zh.md"),
        page_template=Path("scripts/review_page_template.html"), out=args.out)
    print(json.dumps({"status": "LOCAL_13_PLUS_24_PACKETS_CREATED",
                      "files": [str(p) for p in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
