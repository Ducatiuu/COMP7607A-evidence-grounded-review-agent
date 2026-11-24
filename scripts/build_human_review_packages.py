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


def _start_here(slot: int, review_guide: str) -> bytes:
    marker = "# **HTML 审核操作与提交**"
    if marker not in review_guide:
        raise ValueError("review guide is missing its HTML handoff section")
    explanations = review_guide.split(marker, 1)[0].strip()
    return f"""# 人工审核包：Reviewer {slot}（R{slot}）

这份包仅给第 {slot} 位有权使用 SemEval 数据的组员；不要上传 GitHub、云盘公开链接或转发给无授权者。**请先解压，再用 Chrome 或 Edge 双击打开 `review.html`。必须导入本包内对应的 CSV 才能开始审核。**首次审核导入 `01_extraction/reviewer_{slot}.csv` 或 `02_questions/reviewer_{slot}.csv`；下次继续时导入自己上次下载的已填 CSV。无需联网、安装软件或调用模型。

## 两项独立审核与提交

1. **抽取差异：13 条。** 导入抽取 CSV 后，对照原文、Gold、模型预测和原始差异 JSON，选择 `human_decision`。`no_issue` 表示差异确实存在、但两种标注都可接受且无需进一步裁决；选它时 `human_reason` 可以留空。`no_error` 只表示程序比较或数据对齐错误，须填写理由；其余问题判断也须填写理由。页面自动填写审核者 `R{slot}`，在该条首次完成时记录本机日期 `reviewed_at`。后续编辑保留首次完成日期；清空必填判断或理由会回到“未完成”，旧日期仍保留。
2. **正式候选题：120 题，20 包 × 每包 6 题。** 导入题目 CSV 后，按 Pack 核对评论、Gold、题目与候选参考答案。填写四项 `yes/no` 判断；全部为 `yes` 时修改建议和备注可留空。若选 `no`，必须在修改建议或备注中说明。非 Rate 题的分母显示 N/A，导出 CSV 时 `denominator_ok=yes` 仅表示不适用；Rate 题仍需检查分母及零分母。设计为不可回答的题，若缺失条件确实明确，`answerability_ok` 可填 `yes`。

“已完成”仅表示必填字段完整，**不代表判断通过**。“待复核”表示已完成但仍需负责人检查：正式题目有 `no`，或抽取差异选择 `annotation_ambiguity`、`both_or_mixed`、`no_error`、`unresolved`；`no_issue` 不属于待复核。**每次离开前须分别点击“下载当前 CSV”**，把两份 CSV 交回负责人。页面不会自动恢复未导出的编辑；重新导入时会检查只读列与审核者身份。不要修改 ID、评论、Gold、问题、参考答案和 SHA 列，也不要查看正式 A/B/C 预测。两名 Reviewer 须独立完成，不互看答案；分歧由负责人另行裁决，不覆盖原表。

`readonly/` 保留只读核对来源。`test.csv`、`test_gold.json`、`candidate_references.json` 均为本地受限材料；`MANIFEST.json` 记录各文件 SHA-256。浏览页从 Gold 标签按评论 ID 显示辅助计数，供你逐项复核，**不会自动做审核判断**。浏览页展示的参考答案是未审核候选，不是已冻结 Gold。打开网页不会把任何材料发到网络。请参照 `readonly/annotation_guide.md` 和 SemEval 官方标注指南判断 neutral、conflict 与隐含方面。

返回文件建议命名为 `reviewer_{slot}_extraction_filled.csv` 和 `reviewer_{slot}_questions_filled.csv`。若有疑问，写 `unresolved` 或在 `notes` 说明，不要猜测或让模型代填。

---

## 详细审核说明与判断示例

{explanations}
""".encode("utf-8")


def build_packages(*, extraction_root: Path, question_root: Path, test_csv: Path,
                   test_gold: Path, candidate_questions: Path, candidate_references: Path,
                   annotation_guide: Path, review_guide: Path, template: Path, out: Path) -> list[Path]:
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
    review_guide_text = review_guide.read_text(encoding="utf-8")
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
            "START_HERE_ZH.md": _start_here(slot, review_guide_text),
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
        review_guide=Path("docs/human_review_guide_zh.md"),
        template=Path("scripts/review_page_template.html"), out=args.out)
    print(json.dumps({"status": "LOCAL_PACKETS_CREATED", "files": [str(path) for path in paths]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
