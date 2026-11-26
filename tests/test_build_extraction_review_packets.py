import csv
import hashlib
import json
from io import StringIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.build_extraction_review_packets import build_extraction_packets


ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["record_id", "review_text", "gold_aspects", "predicted_aspects",
          "differences", "human_decision", "human_reason", "reviewer", "reviewed_at"]


def _sheet(*, changed_text: bool = False, filled: bool = False) -> bytes:
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for i in range(13):
        writer.writerow({
            "record_id": f"R{i:02d}",
            "review_text": "Changed source" if changed_text and i == 0 else f"Review {i}, good food.",
            "gold_aspects": '[{"category":"food","sentiment":"positive"}]',
            "predicted_aspects": '[{"category":"service","sentiment":"positive"}]',
            "differences": '[{"kind":"missing_category","category":"food"}]',
            "human_decision": "model_error" if filled and i == 0 else "",
            "human_reason": "", "reviewer": "", "reviewed_at": "",
        })
    return stream.getvalue().encode("utf-8")


def _build(tmp_path: Path, *, changed_text: bool = False, filled: bool = False):
    source = tmp_path / "source"
    source.mkdir(parents=True)
    (source / "reviewer_1.csv").write_bytes(_sheet())
    (source / "reviewer_2.csv").write_bytes(_sheet(changed_text=changed_text, filled=filled))
    annotation = tmp_path / "annotation.md"
    annotation.write_text("Synthetic annotation guide", encoding="utf-8")
    return build_extraction_packets(
        extraction_root=source, annotation_guide=annotation,
        guide_template=ROOT / "docs/extraction_packet_guide_zh.md",
        page_template=ROOT / "scripts/extraction_review_page_template.html",
        out=tmp_path / "packets",
    )


def test_extraction_only_packets_are_isolated_blank_and_integrity_checked(tmp_path):
    paths = _build(tmp_path)
    assert len(paths) == 2
    for slot, path in enumerate(paths, start=1):
        with ZipFile(path) as archive:
            names = set(archive.namelist())
            assert archive.testzip() is None
            assert names == {"START_HERE_ZH.md", "review.html",
                             f"01_extraction/reviewer_{slot}.csv",
                             "readonly/annotation_guide.md", "MANIFEST.json"}
            manifest = json.loads(archive.read("MANIFEST.json"))
            assert (manifest["reviewer_slot"], manifest["extraction_rows"],
                    manifest["formal_question_rows"], manifest["human_judgments_filled"]) == (
                        slot, 13, 0, False)
            assert all(hashlib.sha256(archive.read(name)).hexdigest() == digest
                       for name, digest in manifest["files_sha256"].items())
            assert archive.read(f"01_extraction/reviewer_{slot}.csv") == _sheet()
            guide = archive.read("START_HERE_ZH.md").decode("utf-8")
            page = archive.read("review.html").decode("utf-8")
            assert f"Reviewer {slot}（R{slot}）" in guide
            assert f"reviewer_{slot}.csv" in guide
            assert "120 道题" in guide and "不需要审核" in guide
            assert "question_id" not in page and "正式候选题" not in page
            assert f'"slot":{slot}' in page


def test_extraction_only_packets_reject_prefilled_or_misaligned_sheets(tmp_path):
    with pytest.raises(ValueError, match="already contains human judgments"):
        _build(tmp_path / "filled", filled=True)
    with pytest.raises(ValueError, match="different extraction source records"):
        _build(tmp_path / "misaligned", changed_text=True)
