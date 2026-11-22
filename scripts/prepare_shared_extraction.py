"""Prepare one reusable MOCK extraction artifact for offline B/C dry-runs."""

from __future__ import annotations

import argparse
import json

from eval.shared_extraction import prepare_mock_shared_extraction
from src.data_loader import load_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare shared extraction from the synthetic four-record demo")
    parser.add_argument("--mock", action="store_true", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    records = load_csv("data/demo/core.csv")
    _, manifest_sha256, manifest = prepare_mock_shared_extraction(records, args.out)
    print(json.dumps({"mode": manifest.mode, "manifest_sha256": manifest_sha256,
                      "dataset_sha256": manifest.dataset_sha256, "requests": manifest.requests,
                      "retries": manifest.retries, "cache_hits": manifest.cache_hits,
                      "extraction_wall_latency_ms": manifest.extraction_wall_latency_ms}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
