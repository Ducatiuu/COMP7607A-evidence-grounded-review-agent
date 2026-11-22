"""Create local-only candidate splits from licensed SemEval XML files."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.semeval import SemEvalCorpus, parse_restaurant_xml, prepare_candidate_split


def _write_records(path: Path, corpus: SemEvalCorpus, ids: list[str]) -> None:
    by_id = {record.record_id: record for record in corpus.records}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["record_id", "text"])
        writer.writeheader()
        for record_id in ids:
            writer.writerow(by_id[record_id].model_dump())


def _write_gold(path: Path, corpus: SemEvalCorpus, ids: list[str]) -> None:
    by_id = {record.record_id: record for record in corpus.gold}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([by_id[record_id].model_dump(mode="json") for record_id in ids], ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare unreviewed local SemEval split candidates")
    parser.add_argument("--train", required=True)
    parser.add_argument("--test", required=True)
    parser.add_argument("--train-source", required=True, help="actual source URL or accession")
    parser.add_argument("--test-source", required=True, help="actual source URL or accession")
    parser.add_argument("--out", default="data/processed")
    parser.add_argument("--gold-out", default="data/gold")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dev-size", type=int, default=150)
    parser.add_argument("--test-size", type=int, default=600)
    parser.add_argument("--pack-size", type=int, default=30)
    args = parser.parse_args(argv)
    train = parse_restaurant_xml(args.train, source_split="train", source_url=args.train_source)
    test = parse_restaurant_xml(args.test, source_split="test", source_url=args.test_source)
    split = prepare_candidate_split(train, test, seed=args.seed, dev_size=args.dev_size, test_size=args.test_size, pack_size=args.pack_size)
    out = Path(args.out)
    gold_out = Path(args.gold_out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidate_split.json").write_text(split.model_dump_json(indent=2), encoding="utf-8")
    _write_records(out / "dev.csv", train, split.dev_ids)
    _write_records(out / "test.csv", test, split.test_ids)
    _write_gold(gold_out / "dev.json", train, split.dev_ids)
    _write_gold(gold_out / "test.json", test, split.test_ids)
    print(json.dumps({"status": split.status, "manifest_sha256": split.manifest_sha256,
                      "dev_records": len(split.dev_ids), "test_records": len(split.test_ids), "packs": len(split.packs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
