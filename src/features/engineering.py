"""Feature engineering and label construction.

LEAKAGE RULES
- Labels (soh, rul) derive from `capacity` (+ per-battery EOL cycle). `capacity`, `soh`, `rul`
  and `battery_id` are NEVER in FEATURE_COLUMNS (asserted in tests).
- Every feature is computed from the cycle's own voltage/current/temperature/time signals
  (available at inference time) - no future cycles, no target-derived statistics.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

FEATURE_COLUMNS: list[str] = [
    "cycle_number", "ambient_temperature",
    "voltage_mean", "voltage_std", "voltage_min", "voltage_range",
    "current_mean",
    "temperature_mean", "temperature_max", "temperature_rise",
    "discharge_duration", "charge_duration",
]
TARGET_COLUMNS: list[str] = ["soh", "rul"]
FORBIDDEN_FEATURES = {"capacity", "soh", "rul", "battery_id"}


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["voltage_range"] = out["voltage_max"] - out["voltage_min"]
    out["temperature_rise"] = out["temperature_max"] - out["temperature_min"]
    return out


def add_targets(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """SOH (%) = capacity / nominal * 100.
    RUL (cycles) = EOL_cycle - cycle_number (>= 0), EOL = first cycle with SOH <= threshold.
    Batteries that never reach EOL have RUL = NaN (right-censored; not invented)."""
    nominal = cfg["features"]["nominal_capacity_ah"]
    eol = cfg["features"]["eol_soh_percent"]
    out = df.copy()
    out["soh"] = out["capacity"] / nominal * 100.0
    out["rul"] = np.nan
    for bid, grp in out.groupby("battery_id"):
        below = grp[grp["soh"] <= eol]
        if below.empty:
            continue
        eol_cycle = int(below["cycle_number"].min())
        out.loc[grp.index, "rul"] = (eol_cycle - grp["cycle_number"]).clip(lower=0)
    return out


def split_by_battery(df: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, pd.DataFrame]:
    s = cfg["split"]
    groups = {k: list(s[k]) for k in ("train", "val", "test")}
    all_ids = [b for ids in groups.values() for b in ids]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("A battery appears in more than one split")
    present = set(df["battery_id"].unique())
    missing = set(all_ids) - present
    if missing:
        raise ValueError(f"Split references batteries not in data: {sorted(missing)}")
    return {k: df[df["battery_id"].isin(ids)].reset_index(drop=True) for k, ids in groups.items()}
