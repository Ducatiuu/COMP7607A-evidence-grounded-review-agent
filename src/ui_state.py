"""Small local workspace persistence for browser refresh in the demo UI."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from src.data_loader import dataset_fingerprint
from src.schemas import AnswerPayload, ExtractionDataset, RecordSet
from src.schemas.models import StrictModel


class UIWorkspace(StrictModel):
    source_label: str = ""
    records: RecordSet | None = None
    extraction: ExtractionDataset | None = None
    extraction_origin: Literal["synthetic_mock", "provided"] | None = None
    extraction_requests: int | None = Field(default=None, ge=0)
    answer: AnswerPayload | None = None
    comparison: dict[str, AnswerPayload] = Field(default_factory=dict)

    @model_validator(mode="after")
    def aligned(self) -> "UIWorkspace":
        if self.extraction is not None:
            if (self.records is None or self.extraction.fingerprint != dataset_fingerprint(self.records)
                    or self.extraction.records != self.records.records):
                raise ValueError("UI extraction does not match loaded records")
            if self.extraction_origin is None:
                raise ValueError("UI extraction origin is required")
        elif self.extraction_origin is not None:
            raise ValueError("UI extraction origin without extraction")
        return self


def new_session_token() -> str:
    return str(uuid.uuid4())


def _state_path(token: str) -> Path:
    parsed = uuid.UUID(token)
    if str(parsed) != token:
        raise ValueError("invalid UI session token")
    directory = Path(os.environ.get("ABSA_UI_SESSION_DIR", "outputs/ui_sessions"))
    return directory / f"{token}.json"


def load_workspace(token: str) -> UIWorkspace:
    path = _state_path(token)
    if not path.exists():
        return UIWorkspace()
    return UIWorkspace.model_validate_json(path.read_text(encoding="utf-8"))


def save_workspace(token: str, workspace: UIWorkspace) -> None:
    path = _state_path(token)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(workspace.model_dump_json(), encoding="utf-8")
    temporary.replace(path)


def clear_workspace(token: str) -> None:
    _state_path(token).unlink(missing_ok=True)
