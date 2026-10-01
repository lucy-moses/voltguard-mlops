"""Cleaning: remove physically invalid rows and duplicates; keep row order stable."""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils.logging_utils import get_logger

log = get_logger(__name__)


def clean_cycles(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    v = cfg["validation"]
    n0 = len(df)
    out = df.drop_duplicates(["battery_id", "cycle_number"]).copy()
    mask = (
        out.voltage_min.ge(v["voltage_range"][0]) & out.voltage_max.le(v["voltage_range"][1])
        & out.temperature_mean.between(*v["temperature_range"])
        & out.capacity.between(v["min_capacity_ah"], v["max_capacity_ah"])
        & out.discharge_duration.ge(v["min_duration_s"])
    )
    out = out[mask].sort_values(["battery_id", "cycle_number"]).reset_index(drop=True)
    log.info("Cleaning kept %d/%d rows", len(out), n0)
    return out
