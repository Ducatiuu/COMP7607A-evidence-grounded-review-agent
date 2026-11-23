"""Prepare an unreviewed, local-only development pilot from Train-derived dev data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

from eval.questions import QuestionCandidate, build_gold_references
from src.data_loader import load_csv
from src.schemas import Category
from src.semeval import CandidateSplit, GoldRecord


_QUESTION_SPECS = (
    ("count", "How many reviews express negative sentiment about service?", ["count"], None, None),
    ("count", "How many records contain a negative opinion about service?", ["count"], None, None),
    ("rate", "Among reviews mentioning service, what fraction express negative service sentiment?",
     ["numerator", "denominator", "rate"], "aspect_mentions", None),
    ("rate", "Of reviews that mention service, what proportion are negative about service?",
     ["numerator", "denominator", "rate"], "aspect_mentions", None),
    ("selection", "Which reviews praise food and criticize service?", ["selected_record_ids"], None, None),
    ("selection", "Identify review IDs with positive food sentiment and negative service sentiment.",
     ["selected_record_ids"], None, None),
    ("comparison", "Which has more negative reviews, food or service? Include ties.",
     ["comparison_groups", "counts"], None, None),
    ("comparison", "Rank food and service by negative review count; keep ties.",
     ["comparison_groups", "counts"], None, None),
    ("evidence_explanation", "Which of food, service, and price has the most negative reviews? Give source review IDs supporting the result.",
     ["comparison_groups", "counts", "source_record_ids"], None, None),
    ("insufficient_info", "How did negative service reviews change by month?",
     ["insufficient_info"], None, "date"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a Train-derived 30-record/10-question dev pilot candidate")
    parser.add_argument("--split", default="data/processed/candidate_split.json")
    parser.add_argument("--dev", default="data/processed/dev.csv")
    parser.add_argument("--dev-gold", default="data/gold/dev.json")
    parser.add_argument("--out-dir", default="data/processed/dev_pilot")
    parser.add_argument("--references-out", default="data/gold/dev_pilot/references.json")
    parser.add_argument("--seed", type=int, default=31415)
    args = parser.parse_args(argv)

    split_path, dev_path, gold_path = Path(args.split), Path(args.dev), Path(args.dev_gold)
    out_dir, references_path = Path(args.out_dir), Path(args.references_out)
    pilot_path = out_dir / "pilot.csv"
    questions_path = out_dir / "questions.json"
    manifest_path = out_dir / "manifest.json"
    outputs = (pilot_path, questions_path, manifest_path, references_path)
    if len({path.resolve() for path in outputs}) != len(outputs) or any(path.exists() for path in outputs):
        raise ValueError("pilot output already exists or output paths overlap; existing work was not changed")

    split = CandidateSplit.model_validate_json(split_path.read_text(encoding="utf-8"))
    records = load_csv(dev_path)
    dev_ids = [record.record_id for record in records.records]
    if dev_ids != split.dev_ids or len(dev_ids) < 30 or set(dev_ids) & set(split.test_ids):
        raise ValueError("dev CSV must align with the Train-derived split and contain at least 30 non-test records")
    gold = [GoldRecord.model_validate(item) for item in json.loads(gold_path.read_text(encoding="utf-8"))]
    gold_by_id = {item.record_id: item for item in gold}
    if len(gold_by_id) != len(gold) or [item.record_id for item in gold] != dev_ids:
        raise ValueError("dev Gold IDs must align exactly with the Train-derived dev CSV")

    selected = set(random.Random(args.seed).sample(dev_ids, 30))
    pilot_ids = [record_id for record_id in dev_ids if record_id in selected]
    pilot_records = [record for record in records.records if record.record_id in selected]
    questions = [QuestionCandidate(
        question_id=f"DEV-PILOT-Q{number:02d}", pack_id="DEV-PILOT", record_ids=pilot_ids,
        task_type=task_type, wording=wording, expected_fields=expected_fields,
        denominator_spec=denominator, rate_category=Category.SERVICE if task_type == "rate" else None,
        metadata_required=metadata,
    ) for number, (task_type, wording, expected_fields, denominator, metadata) in enumerate(_QUESTION_SPECS, start=1)]
    references = build_gold_references(questions, [gold_by_id[record_id] for record_id in pilot_ids])

    out_dir.mkdir(parents=True, exist_ok=True)
    references_path.parent.mkdir(parents=True, exist_ok=True)
    with pilot_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["record_id", "text"])
        writer.writeheader()
        for record in pilot_records:
            writer.writerow(record.model_dump(mode="json"))
    _write_json(questions_path, [item.model_dump(mode="json") for item in questions])
    _write_json(references_path, [item.model_dump(mode="json") for item in references])
    manifest = {
        "status": "DEV_PILOT_CANDIDATE_UNREVIEWED", "human_review_complete": False,
        "source_split_sha256": split.manifest_sha256, "source_train_sha256": split.train_sha256,
        "dev_csv_sha256": _sha256(dev_path), "dev_gold_sha256": _sha256(gold_path),
        "seed": args.seed, "record_ids": pilot_ids,
        "question_ids": [item.question_id for item in questions],
        "pilot_csv_sha256": _sha256(pilot_path), "questions_sha256": _sha256(questions_path),
        "references_sha256": _sha256(references_path),
    }
    _write_json(manifest_path, manifest)
    print(json.dumps({"status": manifest["status"], "records": len(pilot_ids),
                      "questions": len(questions), "manifest_sha256": _sha256(manifest_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
