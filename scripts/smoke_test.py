"""End-to-end smoke run on SYNTHETIC data in a temp directory (never touches data/raw or mlflow/).

Verifies that the whole pipeline (ingest -> ... -> register) executes. The printed metrics come from
invented data and are NOT results.   Usage: python scripts/smoke_test.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.stages import run_all  # noqa: E402
from tests.synthetic import make_test_config, write_synthetic_mat  # noqa: E402


def main() -> int:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        tmp = Path(d)
        cfg = make_test_config(tmp)
        write_synthetic_mat(Path(cfg["paths"]["raw_dir"]), cfg["ingest"]["batteries"])
        out = run_all(cfg)
        m = out["register_model"]
        print("SMOKE OK (synthetic data - not real results):", m["model_name"], "v" + m["model_version"], m["aliases"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
