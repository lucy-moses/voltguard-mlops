"""Preprocessing stage: validate -> clean -> features -> labels -> split -> fit preprocessor."""
from __future__ import annotations

from typing import Any

import joblib
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.data.clean import clean_cycles
from src.data.validate import validate_cycles
from src.features.engineering import (
    FEATURE_COLUMNS,
    FORBIDDEN_FEATURES,
    TARGET_COLUMNS,
    add_targets,
    build_features,
    split_by_battery,
)
from src.utils.config import resolve, write_json
from src.utils.logging_utils import get_logger

log = get_logger(__name__)


def make_preprocessor() -> Pipeline:
    """Median imputation (e.g. missing charge_duration) + standardisation, fit on TRAIN only."""
    return Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])


def run_preprocess(cfg: dict[str, Any]) -> None:
    assert not (set(FEATURE_COLUMNS) & FORBIDDEN_FEATURES), "Target leakage: forbidden feature present"
    interim = resolve(cfg["paths"]["interim_dir"]) / "cycles.csv"
    df = pd.read_csv(interim)
    report = validate_cycles(df, cfg)
    df = clean_cycles(df, cfg)
    df = add_targets(build_features(df), cfg)
    splits = split_by_battery(df, cfg)

    out_dir = resolve(cfg["paths"]["processed_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    keep = ["battery_id", *FEATURE_COLUMNS, *TARGET_COLUMNS]
    for name, part in splits.items():
        if part.empty:
            raise ValueError(f"Split '{name}' is empty")
        part[keep].to_csv(out_dir / f"{name}.csv", index=False)
        log.info("Split %-5s rows=%d batteries=%s", name, len(part), sorted(part.battery_id.unique()))

    pre = make_preprocessor().fit(splits["train"][FEATURE_COLUMNS])
    pre_dir = resolve(cfg["paths"]["preprocessors_dir"])
    pre_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pre, pre_dir / "preprocessor.joblib")
    write_json({"validation": report, "features": FEATURE_COLUMNS,
                "rows": {k: int(len(v)) for k, v in splits.items()}},
               resolve(cfg["paths"]["metrics_dir"]) / "preprocess_report.json")
