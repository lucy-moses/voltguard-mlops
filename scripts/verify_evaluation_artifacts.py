"""Validate changed evaluation outputs against the DVC lock before registration."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EVALUATION_PATH = "artifacts/metrics/evaluation.json"
BUNDLE_PATH = "artifacts/models/voltguard_bundle.joblib"


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _locked_output(lock_stage: dict, relative_path: str) -> dict:
    for output in lock_stage.get("outs", []):
        if output.get("path") == relative_path:
            return output
    raise ValueError(f"DVC lock is missing the expected evaluation output: {relative_path}")


def verify_evaluation_artifacts(root: Path = ROOT) -> None:
    root = root.resolve()
    lock = yaml.safe_load((root / "dvc.lock").read_text(encoding="utf-8"))
    stage = lock.get("stages", {}).get("evaluate")
    if not isinstance(stage, dict):
        raise ValueError("dvc.lock is missing the evaluate stage.")

    for relative_path in (EVALUATION_PATH, BUNDLE_PATH):
        path = (root / relative_path).resolve()
        if root not in path.parents or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Locked evaluation output is missing or escapes the repository: {relative_path}")
        expected = _locked_output(stage, relative_path).get("md5")
        actual = _md5(path)
        if not expected or expected != actual:
            raise ValueError(f"DVC hash mismatch for evaluation output: {relative_path}")

    try:
        metrics = json.loads((root / EVALUATION_PATH).read_text(encoding="utf-8"))
        test_metrics = metrics["test"]
        for target in ("soh", "rul"):
            values = test_metrics[target]
            for metric in ("rmse", "mae", "r2"):
                value = values[metric]
                if not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"Evaluation metric {target}.{metric} is missing or non-finite.")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Evaluation metrics are incomplete or invalid.") from exc


def main() -> int:
    try:
        verify_evaluation_artifacts()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise SystemExit(f"Evaluation artifact validation failed: {exc}") from None
    print("Verified DVC-locked evaluation metrics and model bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
