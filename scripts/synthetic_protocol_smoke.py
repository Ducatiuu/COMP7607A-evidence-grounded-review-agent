"""Exercise the full 150/600/20x30/120 pipeline on generated synthetic XML only."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.audit_questions import main as audit_main
from scripts.build_questions import main as questions_main
from scripts.build_subsets import main as subsets_main
from scripts.prepare_semeval import main as prepare_main
from src.semeval import CandidateSplit


def write_synthetic_xml(path: Path, *, split: str, count: int) -> None:
    root = ET.Element("sentences")
    for index in range(count):
        sentence = ET.SubElement(root, "sentence", id=f"{split.upper()}{index:04d}")
        if split == "test" and index >= 100:
            variants = [
                ("The food tasted good, but service was slow.", [("food", "positive"), ("service", "negative")]),
                ("The food was cold, while staff were helpful.", [("food", "negative"), ("service", "positive")]),
                ("Service was delayed, though the price was fair.", [("service", "negative"), ("price", "positive")]),
                ("The food was delicious and service was quick.", [("food", "positive"), ("service", "positive")]),
            ]
            review, labels = variants[index % len(variants)]
        else:
            review, labels = "The food was enjoyable.", [("food", "positive")]
        ET.SubElement(sentence, "text").text = f"SYNTHETIC {split.upper()} {index:04d}: {review}"
        categories = ET.SubElement(sentence, "aspectCategories")
        for category, sentiment in labels:
            ET.SubElement(categories, "aspectCategory", category=category, polarity=sentiment)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="outputs/synthetic_protocol")
    args = parser.parse_args(argv)
    output = Path(args.out)
    train, test = output / "raw/train.xml", output / "raw/test.xml"
    processed, gold = output / "processed", output / "gold"
    write_synthetic_xml(train, split="train", count=3041)
    write_synthetic_xml(test, split="test", count=800)
    with contextlib.redirect_stdout(io.StringIO()):
        prepare_main(["--train", str(train), "--test", str(test),
                      "--train-source", "synthetic://train", "--test-source", "synthetic://test",
                      "--out", str(processed), "--gold-out", str(gold)])
        questions_main(["--split", str(processed / "candidate_split.json"), "--gold", str(gold / "test.json"),
                        "--questions-out", str(processed / "candidate_questions.json"),
                        "--references-out", str(gold / "candidate_references.json")])
        subsets_main(["--questions", str(processed / "candidate_questions.json"),
                      "--out", str(processed / "candidate_subsets.json")])
        audit_code = audit_main(["--questions", str(processed / "candidate_questions.json"),
                                 "--references", str(gold / "candidate_references.json"),
                                 "--out", str(processed / "candidate_question_audit.json")])
    audit = json.loads((processed / "candidate_question_audit.json").read_text(encoding="utf-8"))
    split = CandidateSplit.model_validate_json((processed / "candidate_split.json").read_text(encoding="utf-8"))
    print(json.dumps({"mode": "SYNTHETIC_TEST_ONLY", "status": audit["status"],
                      "train_records": 3041, "test_source_records": 800,
                      "dev_records": len(split.dev_ids), "selected_test_records": len(split.test_ids),
                      "packs": audit["pack_count"], "questions": audit["question_count"],
                      "boundary_examples": audit["boundary_examples"],
                      "coverage_gaps": audit["coverage_gaps"]}))
    return audit_code


if __name__ == "__main__":
    raise SystemExit(main())
