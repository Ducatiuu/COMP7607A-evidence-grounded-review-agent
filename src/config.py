"""Offline configuration. Live provider integration needs separate approval."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    model_id: str = "mock"
    prompt_version: str = "extract-v1"
    schema_version: str = "v1"


def load_config() -> AppConfig:
    return AppConfig(model_id=os.environ.get("ABSA_MODEL_ID") or "mock")
