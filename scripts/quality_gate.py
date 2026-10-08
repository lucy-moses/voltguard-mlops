"""CI quality gate: fail the pipeline if held-out test error exceeds project thresholds."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.config import load_config, read_json, resolve  # noqa: E402


def main() -> int:
    cfg = load_config()
    ev = read_json(resolve(cfg["paths"]["metrics_dir"]) / "evaluation.json")["test"]
    q = cfg["quality_gate"]
    checks = [("soh", "max_soh_test_rmse"), ("rul", "max_rul_test_rmse")]
    ok = True
    for target, key in checks:
        if target not in ev:
            print(f"FAIL  {target} test RMSE is missing from evaluation.json")
            ok = False
            continue
        if "rmse" not in ev[target]:
            print(f"FAIL  {target} test RMSE is missing from evaluation.json")
            ok = False
            continue
        rmse = ev[target]["rmse"]
        passed = rmse <= q[key]
        ok &= passed
        print(f"{'PASS' if passed else 'FAIL'}  {target} test RMSE {rmse:.4f} (limit {q[key]})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
