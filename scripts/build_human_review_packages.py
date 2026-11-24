"""Build local, self-contained reviewer packets from unchanged blank review sheets.

The ZIPs contain licensed SemEval-derived text and Gold labels. They are ignored
local handoff artifacts, not material for the public repository.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from io import StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from eval.questions import GoldReference, QuestionCandidate
from scripts.audit_question_review import audit_review_sheets
from src.semeval import GoldRecord


EXTRACTION_EDITABLE = ("human_decision", "human_reason", "reviewer", "reviewed_at")
QUESTION_EDITABLE = ("reviewer_id", "wording_ok", "answerability_ok", "denominator_ok",
                     "reference_ok", "proposed_edit", "notes")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _csv(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    with StringIO(data.decode("utf-8-sig"), newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("missing or duplicate CSV headers")
        rows = list(reader)
    if any(None in row or any(not isinstance(value, str) for value in row.values()) for row in rows):
        raise ValueError("malformed review CSV")
    return reader.fieldnames, rows


def _validate_sheets(extraction: list[dict[str, str]], questions: list[dict[str, str]]) -> None:
    if len(extraction) != 13 or len(questions) != 120:
        raise ValueError("expected 13 extraction and 120 question rows")
    if any(any(row[field].strip() for field in EXTRACTION_EDITABLE) for row in extraction):
        raise ValueError("extraction sheet already contains human work")
    if any(any(row[field].strip() for field in QUESTION_EDITABLE) for row in questions):
        raise ValueError("question sheet already contains human work")
    if len({row["record_id"] for row in extraction}) != 13:
        raise ValueError("duplicate extraction record IDs")
    if len({row["question_id"] for row in questions}) != 120:
        raise ValueError("duplicate question IDs")


def _zip_write(archive: ZipFile, name: str, data: bytes) -> None:
    entry = ZipInfo(name, date_time=(2026, 11, 24, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.external_attr = 0o644 << 16
    archive.writestr(entry, data)


def _embedded_json(value: dict) -> str:
    """Keep source text inert inside an HTML application/json script element."""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _start_here(slot: int) -> bytes:
    return f"""# 人工审核包：Reviewer {slot}

这份包仅给第 {slot} 位有权使用 SemEval 数据的组员；不要上传 GitHub、云盘公开链接或转发给无授权者。解压后双击 `review.html`，无需安装软件、联网或调用模型。也可用 VS Code 编辑两个 CSV；Excel 导入时把 ID 和 JSON 列设为文本，保存为 UTF-8 CSV。

## 两项独立审核

1. **抽取差异：13 条。** 打开“抽取差异”页，对照原文、Gold 和模型预测，在 `human_decision` 选 `model_error`、`annotation_ambiguity`、`both_or_mixed`、`no_error` 或 `unresolved`；填写 `human_reason`、`reviewer`、`reviewed_at`。多个差异原因不同则在理由中逐项说明。
2. **正式候选题：120 题，20 包 × 每包 6 题。** 打开“正式题目”页，按 Pack 对照 30 条评论与 Gold 标签，检查问题和候选参考答案。填写 `reviewer_id`、`wording_ok`、`answerability_ok`、`denominator_ok`、`reference_ok`、`proposed_edit`、`notes`。四个判断字段只能选 `yes` 或 `no`；非比例题的 `denominator_ok` 按审核协议填 `yes`。设计为不可回答的题，若缺失条件确实明确，`answerability_ok` 可填 `yes`。

浏览页会在这台电脑的浏览器本地保存编辑进度。**每次离开前仍须分别点击“下载当前 CSV”**，把两份完成的 CSV 交回负责人；本地浏览器存储不能代替交付文件。“导入已填 CSV”可恢复进度，并会检查原始只读列未被改动。不要修改 ID、评论、Gold、问题、参考答案和 SHA 列，也不要查看正式 A/B/C 预测。两名 Reviewer 须独立完成，不互看答案；分歧由负责人另行裁决，不覆盖原表。

`readonly/` 保留只读核对来源。`test.csv`、`test_gold.json`、`candidate_references.json` 均为本地受限材料；`MANIFEST.json` 记录各文件 SHA-256。浏览页从 Gold 标签按评论 ID 显示辅助计数，供你逐项复核，**不会自动做审核判断**。浏览页展示的参考答案是未审核候选，不是已冻结 Gold。打开网页不会把任何材料发到网络。请参照 `readonly/annotation_guide.md` 和 SemEval 官方标注指南判断 neutral、conflict 与隐含方面。

返回文件建议命名为 `reviewer_{slot}_extraction_filled.csv` 和 `reviewer_{slot}_questions_filled.csv`。若有疑问，写 `unresolved` 或在 `notes` 说明，不要猜测或让模型代填。
""".encode("utf-8")


def build_packages(*, extraction_root: Path, question_root: Path, test_csv: Path,
                   test_gold: Path, candidate_questions: Path, candidate_references: Path,
                   annotation_guide: Path, template: Path, out: Path) -> list[Path]:
    if out.exists():
        raise FileExistsError(f"output directory already exists: {out}")
    source = {
        "test.csv": test_csv.read_bytes(),
        "test_gold.json": test_gold.read_bytes(),
        "candidate_questions.json": candidate_questions.read_bytes(),
        "candidate_references.json": candidate_references.read_bytes(),
        "annotation_guide.md": annotation_guide.read_bytes(),
    }
    qmodels = [QuestionCandidate.model_validate(item) for item in json.loads(source["candidate_questions.json"])]
    rmodels = [GoldReference.model_validate(item) for item in json.loads(source["candidate_references.json"])]
    audit = audit_review_sheets(qmodels, rmodels, question_root / "reviewer_1.csv",
                                question_root / "reviewer_2.csv")
    if audit["status"] != "PENDING_HUMAN_REVIEW" or audit["missing_judgments"] != 960:
        raise ValueError("candidate review sheets are no longer untouched blanks")
    _, test_rows = _csv(source["test.csv"])
    gold = [GoldRecord.model_validate(item) for item in json.loads(source["test_gold.json"])]
    if len(test_rows) != 600 or len(gold) != 600 or [r["record_id"] for r in test_rows] != [r.record_id for r in gold]:
        raise ValueError("test CSV and Gold record IDs do not align exactly")
    if len({r["record_id"] for r in test_rows}) != 600:
        raise ValueError("duplicate test record IDs")
    test_ids = {r["record_id"] for r in test_rows}
    if {record_id for question in qmodels for record_id in question.record_ids} != test_ids:
        raise ValueError("candidate question scopes do not cover the exact test records")
    html_template = template.read_text(encoding="utf-8")
    if "__REVIEW_DATA__" not in html_template:
        raise ValueError("review HTML template has no data marker")
    pending: list[tuple[Path, dict[str, bytes]]] = []
    first_extraction_sources: list[dict[str, str]] | None = None
    for slot in (1, 2):
        extract_bytes = (extraction_root / f"reviewer_{slot}.csv").read_bytes()
        question_bytes = (question_root / f"reviewer_{slot}.csv").read_bytes()
        ex_fields, ex_rows = _csv(extract_bytes)
        qu_fields, qu_rows = _csv(question_bytes)
        _validate_sheets(ex_rows, qu_rows)
        unchanged = [{key: value for key, value in row.items() if key not in EXTRACTION_EDITABLE}
                     for row in ex_rows]
        if first_extraction_sources is None:
            first_extraction_sources = unchanged
        elif unchanged != first_extraction_sources:
            raise ValueError("two extraction reviewers have different source rows")
        review_data = {
            "slot": slot, "extraction": ex_rows, "questions": qu_rows,
            "extractionFields": ex_fields, "questionFields": qu_fields,
            "testRecords": test_rows,
            "goldRecords": [item.model_dump(mode="json") for item in gold],
            "sourceHashes": {name: _sha(data) for name, data in source.items()},
            "sheetHashes": {"extraction": _sha(extract_bytes), "questions": _sha(question_bytes)},
        }
        page = html_template.replace("__REVIEW_DATA__", _embedded_json(review_data)).encode("utf-8")
        files = {
            "START_HERE_ZH.md": _start_here(slot),
            "review.html": page,
            f"01_extraction/reviewer_{slot}.csv": extract_bytes,
            f"02_questions/reviewer_{slot}.csv": question_bytes,
            **{f"readonly/{name}": data for name, data in source.items()},
        }
        manifest = {
            "status": "PENDING_INDEPENDENT_HUMAN_REVIEW",
            "reviewer_slot": slot, "extraction_rows": 13, "question_rows": 120,
            "formal_predictions_included": False, "human_judgments_filled": False,
            "source_questions_sha256": audit["questions_sha256"],
            "source_references_sha256": audit["references_sha256"],
            "files_sha256": {name: _sha(data) for name, data in sorted(files.items())},
        }
        files["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        pending.append((out / f"reviewer_{slot}_anonymous.zip", files))
    out.mkdir(parents=True)
    for target, files in pending:
        with ZipFile(target, "x") as archive:
            for name, data in sorted(files.items()):
                _zip_write(archive, name, data)
    return [target for target, _ in pending]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local-only independent human review ZIPs")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    paths = build_packages(
        extraction_root=Path("outputs/extraction_review_v8_2026-11-24"),
        question_root=Path("data/gold/question_review/0ba746858bfd"),
        test_csv=Path("data/processed/test.csv"), test_gold=Path("data/gold/test.json"),
        candidate_questions=Path("data/processed/candidate_questions.json"),
        candidate_references=Path("data/gold/candidate_references.json"),
        annotation_guide=Path("docs/annotation_guide.md"),
        template=Path("scripts/review_page_template.html"), out=args.out)
    print(json.dumps({"status": "LOCAL_PACKETS_CREATED", "files": [str(path) for path in paths]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
