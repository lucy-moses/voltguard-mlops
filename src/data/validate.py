"""Data validation: schema + sanity checks. Hard failures raise; soft findings are reported."""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.data.ingest import INTERIM_COLUMNS
from src.utils.logging_utils import get_logger

log = get_logger(__name__)


class DataValidationError(ValueError):
    """Raised when data violates a hard requirement."""


def validate_cycles(df: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    v = cfg["validation"]
    missing = [c for c in INTERIM_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(f"Missing columns: {missing}")
    if df.empty:
        raise DataValidationError("Dataset is empty")

    null_frac = df.drop(columns=["charge_duration"]).isna().mean()
    bad = null_frac[null_frac > v["max_null_fraction"]]
    if not bad.empty:
        raise DataValidationError(f"Too many nulls: {bad.to_dict()}")

    report = {
        "n_rows": int(len(df)),
        "n_batteries": int(df["battery_id"].nunique()),
        "duplicates": int(df.duplicated(["battery_id", "cycle_number"]).sum()),
        "voltage_out_of_range": int(((df.voltage_min < v["voltage_range"][0]) | (df.voltage_max > v["voltage_range"][1])).sum()),
        "temperature_out_of_range": int(((df.temperature_mean < v["temperature_range"][0]) | (df.temperature_mean > v["temperature_range"][1])).sum()),
        "capacity_out_of_range": int(((df.capacity < v["min_capacity_ah"]) | (df.capacity > v["max_capacity_ah"])).sum()),
        "non_positive_duration": int((df.discharge_duration < v["min_duration_s"]).sum()),
        "null_charge_duration": int(df.charge_duration.isna().sum()),
    }
    log.info("Validation report: %s", report)
    return report
