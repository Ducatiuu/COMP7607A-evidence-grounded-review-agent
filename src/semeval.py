"""Local SemEval restaurant XML parsing and auditable candidate sampling."""

from __future__ import annotations

import hashlib
import json
import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.schemas import Category, Record, RecordSet, Sentiment
from src.schemas.models import StrictModel


class GoldAnnotation(StrictModel):
    category: Category
    sentiment: Sentiment


class GoldRecord(StrictModel):
    record_id: str = Field(min_length=1)
    aspects: list[GoldAnnotation]

    @model_validator(mode="after")
    def unique_categories(self) -> "GoldRecord":
        categories = [aspect.category for aspect in self.aspects]
        if len(set(categories)) != len(categories):
            raise ValueError(f"duplicate gold category for {self.record_id}")
        return self


class SemEvalCorpus(StrictModel):
    source_split: Literal["train", "test"]
    source_url: str = Field(min_length=1)
    file_sha256: str = Field(min_length=64, max_length=64)
    records: list[Record]
    gold: list[GoldRecord]
    duplicate_exact_annotation_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def aligned(self) -> "SemEvalCorpus":
        RecordSet(records=self.records)
        ids = [record.record_id for record in self.records]
        if [record.record_id for record in self.gold] != ids:
            raise ValueError("gold IDs must align with records")
        return self


class DuplicateGroup(StrictModel):
    record_ids: list[str]
    conflicting_labels: bool


class CandidateSplit(StrictModel):
    status: Literal["CANDIDATE_UNREVIEWED"] = "CANDIDATE_UNREVIEWED"
    seed: int
    train_sha256: str
    test_sha256: str
    train_source_url: str
    test_source_url: str
    dev_ids: list[str]
    test_ids: list[str]
    packs: list[list[str]]
    train_duplicate_groups: list[DuplicateGroup]
    test_duplicate_groups: list[DuplicateGroup]
    train_duplicate_exact_annotation_ids: list[str] = Field(default_factory=list)
    test_duplicate_exact_annotation_ids: list[str] = Field(default_factory=list)
    cross_split_train_ids: list[str]
    conflict_excluded_train_ids: list[str]
    conflict_excluded_test_ids: list[str]
    dev_label_counts: dict[str, int]
    test_label_counts: dict[str, int]
    manifest_sha256: str

    @model_validator(mode="after")
    def pack_alignment(self) -> "CandidateSplit":
        flattened = [record_id for pack in self.packs for record_id in pack]
        if flattened != self.test_ids or len(flattened) != len(set(flattened)):
            raise ValueError("packs must partition selected test IDs exactly")
        if len(self.dev_ids) != len(set(self.dev_ids)) or set(self.dev_ids) & set(self.test_ids):
            raise ValueError("dev/test IDs overlap or repeat")
        return self


def parse_restaurant_xml(path: str | Path, *, source_split: Literal["train", "test"], source_url: str) -> SemEvalCorpus:
    raw = Path(path).read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("DTD and entities are not accepted")
    root = ET.fromstring(raw)
    if root.tag != "sentences":
        raise ValueError("expected <sentences> root")
    records: list[Record] = []
    gold: list[GoldRecord] = []
    duplicate_exact_annotation_ids: list[str] = []
    for sentence in root.findall("sentence"):
        record_id = sentence.get("id")
        text = sentence.findtext("text")
        if not record_id or text is None:
            raise ValueError("sentence missing id or text")
        record = Record(record_id=record_id, text=text)
        annotations = []
        seen_categories: dict[Category, Sentiment] = {}
        container = sentence.find("aspectCategories")
        if container is not None:
            for aspect in container.findall("aspectCategory"):
                category = aspect.get("category")
                polarity = aspect.get("polarity")
                if category is None:
                    raise ValueError(f"missing aspect category for {record_id}")
                if polarity is None:
                    raise ValueError(f"missing aspect polarity for {record_id}; Phase B input is not Gold test data")
                annotation = GoldAnnotation(category=category.lower(), sentiment=polarity.lower())
                previous = seen_categories.get(annotation.category)
                if previous is not None:
                    if previous != annotation.sentiment:
                        raise ValueError(f"duplicate gold category with conflicting polarity for {record_id}")
                    if record_id not in duplicate_exact_annotation_ids:
                        duplicate_exact_annotation_ids.append(record_id)
                    continue
                seen_categories[annotation.category] = annotation.sentiment
                annotations.append(annotation)
        records.append(record)
        gold.append(GoldRecord(record_id=record_id, aspects=annotations))
    if not records:
        raise ValueError("no sentences found")
    if not any(item.aspects for item in gold):
        raise ValueError("no category-polarity gold labels found; Gold XML required")
    return SemEvalCorpus(source_split=source_split, source_url=source_url,
                         file_sha256=hashlib.sha256(raw).hexdigest(), records=records, gold=gold,
                         duplicate_exact_annotation_ids=duplicate_exact_annotation_ids)


def normalized_dedup_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _deduplicate(corpus: SemEvalCorpus) -> tuple[list[Record], list[DuplicateGroup]]:
    groups: dict[str, list[tuple[Record, GoldRecord]]] = {}
    gold_by_id = {item.record_id: item for item in corpus.gold}
    for record in corpus.records:
        groups.setdefault(normalized_dedup_key(record.text), []).append((record, gold_by_id[record.record_id]))
    unique: list[Record] = []
    duplicates: list[DuplicateGroup] = []
    for entries in groups.values():
        unique.append(entries[0][0])
        if len(entries) > 1:
            label_sets = [{(aspect.category, aspect.sentiment) for aspect in gold.aspects} for _, gold in entries]
            duplicates.append(DuplicateGroup(record_ids=[record.record_id for record, _ in entries],
                                             conflicting_labels=any(labels != label_sets[0] for labels in label_sets[1:])))
    return unique, duplicates


def prepare_candidate_split(train: SemEvalCorpus, test: SemEvalCorpus, *, seed: int = 42,
                            dev_size: int = 150, test_size: int = 600, pack_size: int = 30) -> CandidateSplit:
    if train.source_split != "train" or test.source_split != "test":
        raise ValueError("train and test source roles are required")
    if min(dev_size, test_size, pack_size) <= 0 or test_size % pack_size:
        raise ValueError("positive sizes and exact pack divisibility are required")
    unique_train, train_duplicates = _deduplicate(train)
    unique_test, test_duplicates = _deduplicate(test)
    train_conflicts = {record_id for group in train_duplicates if group.conflicting_labels for record_id in group.record_ids}
    test_conflicts = {record_id for group in test_duplicates if group.conflicting_labels for record_id in group.record_ids}
    test_keys = {normalized_dedup_key(record.text) for record in test.records}
    overlap = [record.record_id for record in unique_train if normalized_dedup_key(record.text) in test_keys]
    excluded_train = set(overlap) | train_conflicts
    dev_pool = [record for record in unique_train if record.record_id not in excluded_train]
    test_pool = [record for record in unique_test if record.record_id not in test_conflicts]
    if len(dev_pool) < dev_size or len(test_pool) < test_size:
        raise ValueError(f"insufficient distinct records: dev pool {len(dev_pool)}/{dev_size}, test pool {len(test_pool)}/{test_size}")
    rng = random.Random(seed)
    dev_selected = set(rng.sample([record.record_id for record in dev_pool], dev_size))
    test_selected = set(rng.sample([record.record_id for record in test_pool], test_size))
    dev_ids = [record.record_id for record in dev_pool if record.record_id in dev_selected]
    test_ids = [record.record_id for record in test_pool if record.record_id in test_selected]
    packs = [test_ids[index:index + pack_size] for index in range(0, test_size, pack_size)]

    def label_counts(corpus: SemEvalCorpus, ids: list[str]) -> dict[str, int]:
        selected = set(ids)
        counts: dict[str, int] = {}
        for record in corpus.gold:
            if record.record_id in selected:
                for aspect in record.aspects:
                    key = f"{aspect.category.value}|{aspect.sentiment.value}"
                    counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    material = {
        "status": "CANDIDATE_UNREVIEWED", "seed": seed,
        "train_sha256": train.file_sha256, "test_sha256": test.file_sha256,
        "train_source_url": train.source_url, "test_source_url": test.source_url,
        "dev_ids": dev_ids, "test_ids": test_ids, "packs": packs,
        "train_duplicate_groups": [group.model_dump(mode="json") for group in train_duplicates],
        "test_duplicate_groups": [group.model_dump(mode="json") for group in test_duplicates],
        "train_duplicate_exact_annotation_ids": train.duplicate_exact_annotation_ids,
        "test_duplicate_exact_annotation_ids": test.duplicate_exact_annotation_ids,
        "cross_split_train_ids": overlap,
        "conflict_excluded_train_ids": sorted(train_conflicts),
        "conflict_excluded_test_ids": sorted(test_conflicts),
        "dev_label_counts": label_counts(train, dev_ids),
        "test_label_counts": label_counts(test, test_ids),
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return CandidateSplit(**material, manifest_sha256=digest)
