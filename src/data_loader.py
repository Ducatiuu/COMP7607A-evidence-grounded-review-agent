"""CSV ingress for review records; never silently drops invalid rows."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import TextIO

from src.schemas import Record, RecordSet


class DataLoadError(ValueError):
    pass


def load_csv(path: str | Path) -> RecordSet:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        return read_csv(stream)


def read_csv(stream: TextIO) -> RecordSet:
    reader = csv.DictReader(_reject_blank_physical_rows(stream))
    if not reader.fieldnames or "text" not in reader.fieldnames:
        raise DataLoadError("CSV requires a text column")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise DataLoadError("duplicate CSV header")
    records: list[Record] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise DataLoadError(f"row {row_number}: more values than headers")
        try:
            raw_id = row.get("record_id")
            records.append(Record.model_validate({
                "record_id": raw_id.strip() if isinstance(raw_id, str) else None,
                "text": row["text"],
            }))
        except Exception as exc:
            raise DataLoadError(f"row {row_number}: invalid record: {exc}") from exc
    try:
        return RecordSet(records=records)
    except ValueError as exc:
        raise DataLoadError(str(exc)) from exc


def _reject_blank_physical_rows(stream: TextIO):
    """Reject empty rows, while allowing blank lines inside a quoted CSV field."""
    in_quotes = False
    for line_number, line in enumerate(stream, start=1):
        if not in_quotes and not line.strip():
            raise DataLoadError(f"line {line_number}: blank CSV row")
        index = 0
        while index < len(line):
            if line[index] == '"':
                if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                    index += 2
                    continue
                in_quotes = not in_quotes
            index += 1
        yield line


def dataset_fingerprint(records: RecordSet) -> str:
    payload = [{"record_id": r.record_id, "text": r.text} for r in records.records]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
