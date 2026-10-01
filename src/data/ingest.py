"""Data ingestion: NASA PCoE Li-ion battery .mat files -> one row per discharge cycle.

NASA file layout (per battery file <ID>.mat):
    <ID>.cycle -> array of structs {type, ambient_temperature, time, data}
    type in {'charge', 'discharge', 'impedance'}
    discharge data fields: Voltage_measured, Current_measured, Temperature_measured,
                           Current_load, Voltage_load, Time, Capacity
    charge data fields:    Voltage_measured, Current_measured, Temperature_measured,
                           Current_charge, Voltage_charge, Time
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.io import loadmat

from src.utils.config import resolve
from src.utils.logging_utils import get_logger

log = get_logger(__name__)

INTERIM_COLUMNS = [
    "battery_id", "cycle_number", "ambient_temperature",
    "voltage_mean", "voltage_std", "voltage_min", "voltage_max",
    "current_mean", "temperature_mean", "temperature_max", "temperature_min",
    "discharge_duration", "charge_duration", "capacity",
]


class DataIngestionError(RuntimeError):
    """Raised when raw battery files are missing or malformed."""


def _arr(x: Any) -> np.ndarray:
    return np.atleast_1d(np.asarray(x, dtype=float))


def parse_cycles(battery_id: str, cycles: Any) -> pd.DataFrame:
    """Turn the NASA cycle list into a per-discharge-cycle table.

    `charge_duration` comes from the charge cycle immediately preceding a discharge
    (NaN when there is none). `capacity` is kept ONLY as the label source (SOH/RUL);
    it is never a model feature.
    """
    rows: list[dict[str, Any]] = []
    pending_charge = np.nan
    n_discharge = 0
    for cyc in np.atleast_1d(cycles):
        ctype = str(cyc["type"]).strip().lower()
        d = cyc["data"]
        if ctype == "charge":
            t = _arr(d["Time"])
            pending_charge = float(t[-1] - t[0]) if t.size > 1 else np.nan
        elif ctype == "discharge":
            v, i = _arr(d["Voltage_measured"]), _arr(d["Current_measured"])
            temp, t = _arr(d["Temperature_measured"]), _arr(d["Time"])
            if min(v.size, i.size, temp.size, t.size) < 2:
                log.warning("%s: skipping discharge with <2 samples", battery_id)
                continue
            n_discharge += 1
            rows.append({
                "battery_id": battery_id,
                "cycle_number": n_discharge,
                "ambient_temperature": float(np.atleast_1d(cyc["ambient_temperature"])[0]),
                "voltage_mean": v.mean(), "voltage_std": v.std(ddof=0),
                "voltage_min": v.min(), "voltage_max": v.max(),
                "current_mean": i.mean(),
                "temperature_mean": temp.mean(), "temperature_max": temp.max(),
                "temperature_min": temp.min(),
                "discharge_duration": float(t[-1] - t[0]),
                "charge_duration": pending_charge,
                "capacity": float(_arr(d["Capacity"])[0]),
            })
            pending_charge = np.nan
    return pd.DataFrame(rows, columns=INTERIM_COLUMNS)


def find_mat_file(raw_dir: Path, battery_id: str) -> Path:
    matches = sorted(raw_dir.rglob(f"{battery_id}.mat"))
    if not matches:
        raise DataIngestionError(
            f"{battery_id}.mat not found under {raw_dir}. Run `python scripts/download_data.py` "
            "or `dvc pull`, or place the NASA files as described in data/README.md."
        )
    return matches[0]


def parse_battery_file(path: Path, battery_id: str) -> pd.DataFrame:
    try:
        mat = loadmat(str(path), simplify_cells=True)
    except Exception as exc:  # noqa: BLE001
        raise DataIngestionError(f"Cannot read {path}: {exc}") from exc
    if battery_id not in mat or "cycle" not in mat[battery_id]:
        raise DataIngestionError(f"{path} does not contain '{battery_id}.cycle'")
    return parse_cycles(battery_id, mat[battery_id]["cycle"])


def run_ingestion(cfg: dict[str, Any]) -> Path:
    raw_dir = resolve(cfg["paths"]["raw_dir"])
    out = resolve(cfg["paths"]["interim_dir"]) / "cycles.csv"
    frames = []
    for bid in cfg["ingest"]["batteries"]:
        df = parse_battery_file(find_mat_file(raw_dir, bid), bid)
        if len(df) < cfg["ingest"]["min_discharge_cycles"]:
            raise DataIngestionError(f"{bid}: only {len(df)} discharge cycles")
        log.info("Ingested %s: %d discharge cycles", bid, len(df))
        frames.append(df)
    out.parent.mkdir(parents=True, exist_ok=True)
    full = pd.concat(frames, ignore_index=True)
    full.to_csv(out, index=False)
    log.info("Wrote %s (%d rows)", out, len(full))
    return out
