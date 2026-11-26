"""Build two local-only, extraction-only reviewer packets from untouched blank sheets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile

from scripts.build_human_review_packages import (
    EXTRACTION_EDITABLE,
    _csv,
    _embedded_json,
    _sha,
    _zip_write,
)


EXPECTED_FIELDS = (
    "record_id", "review_text", "gold_aspects", "predicted_aspects", "differences",
    *EXTRACTION_EDITABLE,
)


def build_extraction_packets(*, extraction_root: Path, annotation_guide: Path,
                             guide_template: Path, page_template: Path,
                             out: Path) -> list[Path]:
    if out.exists():
        raise FileExistsError(f"output directory already exists: {out}")
    guide_source = guide_template.read_text(encoding="utf-8")
    page_source = page_template.read_text(encoding="utf-8")
    if "__SLOT__" not in guide_source or page_source.count("__REVIEW_DATA__") != 1:
        raise ValueError("reviewer packet template markers are missing")
    annotation_bytes = annotation_guide.read_bytes()
    planned: list[tuple[Path, dict[str, bytes]]] = []
    first_readonly: list[dict[str, str]] | None = None
    for slot in (1, 2):
        source_bytes = (extraction_root / f"reviewer_{slot}.csv").read_bytes()
        fields, rows = _csv(source_bytes)
        if tuple(fields) != EXPECTED_FIELDS or len(rows) != 13:
            raise ValueError("expected the exact 13-record extraction review schema")
        if len({row["record_id"] for row in rows}) != 13:
            raise ValueError("duplicate extraction record IDs")
        if any(any(row[field].strip() for field in EXTRACTION_EDITABLE) for row in rows):
            raise ValueError("extraction sheet already contains human judgments")
        readonly = [{key: value for key, value in row.items() if key not in EXTRACTION_EDITABLE}
                    for row in rows]
        if first_readonly is None:
            first_readonly = readonly
        elif readonly != first_readonly:
            raise ValueError("reviewers have different extraction source records")
        data = {"slot": slot, "fields": fields, "rows": rows}
        page = page_source.replace("__REVIEW_DATA__", _embedded_json(data)).encode("utf-8")
        guide = guide_source.replace("__SLOT__", str(slot)).encode("utf-8")
        files = {
            "START_HERE_ZH.md": guide,
            "review.html": page,
            f"01_extraction/reviewer_{slot}.csv": source_bytes,
            "readonly/annotation_guide.md": annotation_bytes,
        }
        manifest = {
            "status": "PENDING_INDEPENDENT_HUMAN_REVIEW",
            "reviewer_slot": slot,
            "extraction_rows": 13,
            "formal_question_rows": 0,
            "human_judgments_filled": False,
            "source_sheet_sha256": _sha(source_bytes),
            "files_sha256": {name: _sha(data) for name, data in sorted(files.items())},
        }
        files["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        planned.append((out / f"reviewer_{slot}_extraction_only.zip", files))
    out.mkdir(parents=True)
    for target, files in planned:
        with ZipFile(target, "x") as archive:
            for name, data in sorted(files.items()):
                _zip_write(archive, name, data)
    return [target for target, _ in planned]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build 13-record extraction review ZIPs")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    paths = build_extraction_packets(
        extraction_root=Path("outputs/extraction_review_v8_2026-11-24"),
        annotation_guide=Path("docs/annotation_guide.md"),
        guide_template=Path("docs/extraction_packet_guide_zh.md"),
        page_template=Path("scripts/extraction_review_page_template.html"),
        out=args.out,
    )
    print(json.dumps({"status": "LOCAL_EXTRACTION_PACKETS_CREATED",
                      "files": [str(path) for path in paths]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
