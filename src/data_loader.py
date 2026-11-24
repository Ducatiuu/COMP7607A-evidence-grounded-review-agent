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


def load_csv(path: str | Path, *, text_column: str = "text", id_column: str = "record_id",
             preserve_explicit_ids: bool = False) -> RecordSet:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        return read_csv(stream, text_column=text_column, id_column=id_column,
                        preserve_explicit_ids=preserve_explicit_ids)


def read_csv(stream: TextIO, *, text_column: str = "text", id_column: str = "record_id",
             preserve_explicit_ids: bool = False) -> RecordSet:
    if not text_column or not id_column or text_column == id_column:
        raise DataLoadError("distinct nonempty text and ID column names required")
    reader = csv.DictReader(_reject_blank_physical_rows(stream))
    if not reader.fieldnames or text_column not in reader.fieldnames:
        raise DataLoadError(f"CSV requires a {text_column!r} column")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise DataLoadError("duplicate CSV header")
    records: list[Record] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise DataLoadError(f"row {row_number}: more values than headers")
        try:
            text = row[text_column]
            raw_id = row.get(id_column)
            if id_column in reader.fieldnames:
                if not isinstance(raw_id, str) or not raw_id.strip():
                    raise DataLoadError("blank record ID")
                record_id = raw_id if preserve_explicit_ids else raw_id.strip()
            elif isinstance(text, str):
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
                record_id = f"auto-{row_number - 1:06d}-{digest}"
            else:
                record_id = None
            records.append(Record.model_validate({
                "record_id": record_id,
                "text": text,
            }))
        except Exception as exc:
            raise DataLoadError(f"row {row_number}: invalid record: {exc}") from exc
    if not records:
        raise DataLoadError("CSV has no review records")
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
