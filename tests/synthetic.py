"""SYNTHETIC battery data generator - FOR TESTS AND SMOKE RUNS ONLY.

Writes .mat files in the NASA PCoE layout so the real ingestion code path is exercised.
Values are invented; results obtained on this data say NOTHING about real batteries and must
never be reported as experimental results.
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from scipy.io import savemat

from src.utils.config import load_config

_DISCHARGE_FIELDS = ["Voltage_measured", "Current_measured", "Temperature_measured",
                     "Current_load", "Voltage_load", "Time", "Capacity"]
_CHARGE_FIELDS = ["Voltage_measured", "Current_measured", "Temperature_measured",
                  "Current_charge", "Voltage_charge", "Time"]


def _struct(fields: list[str], values: list) -> np.ndarray:
    arr = np.empty((1, 1), dtype=[(f, "O") for f in fields])
    for f, v in zip(fields, values):
        arr[0, 0][f] = v
    return arr


def make_battery_cycles(n_cycles: int, seed: int, fade_per_cycle: float = 0.006, n_samples: int = 40):
    rng = np.random.default_rng(seed)
    cycles = []
    for i in range(1, n_cycles + 1):
        cap = 2.0 - fade_per_cycle * i + rng.normal(0, 0.01)
        dur = max(cap / 2.0 * 3600.0, 60.0)
        t_c = np.linspace(0, 10000 + 5 * i, n_samples)
        vc = np.linspace(3.5, 4.2, n_samples)
        ch = _struct(_CHARGE_FIELDS, [vc, np.full(n_samples, 1.5), np.full(n_samples, 25.0 + 0.01 * i),
                                      np.full(n_samples, 1.5), vc, t_c])
        cycles.append(("charge", ch))
        t = np.linspace(0, dur, n_samples)
        v = np.linspace(4.2 - 0.001 * i, 2.7, n_samples) + rng.normal(0, 0.005, n_samples)
        temp = 30 + 0.02 * i + 5 * np.linspace(0, 1, n_samples) + rng.normal(0, 0.1, n_samples)
        dis = _struct(_DISCHARGE_FIELDS, [v, np.full(n_samples, -2.0), temp, np.full(n_samples, 2.0), v, t, cap])
        cycles.append(("discharge", dis))
    return cycles


def write_synthetic_mat(out_dir: Path, battery_ids: list[str], n_cycles: int = 130) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, bid in enumerate(battery_ids):
        cyc = make_battery_cycles(n_cycles, seed=k, fade_per_cycle=0.0055 + 0.0003 * k)
        arr = np.empty((1, len(cyc)), dtype=[("type", "O"), ("ambient_temperature", "O"),
                                             ("time", "O"), ("data", "O")])
        for j, (ctype, data) in enumerate(cyc):
            arr[0, j] = (ctype, 24, np.array([2008.0]), data)
        savemat(str(out_dir / f"{bid}.mat"), {bid: {"cycle": arr}})


def make_test_config(tmp: Path, batteries=("B0005", "B0006", "B0007", "B0018"), n_models_small: bool = True) -> dict:
    """Config with all paths redirected into `tmp` and a fast, small model zoo."""
    cfg = copy.deepcopy(load_config())
    for k in cfg["paths"]:
        cfg["paths"][k] = str(tmp / k)
    cfg["mlflow"]["tracking_uri"] = f"sqlite:///{tmp}/mlflow.db"
    cfg["mlflow"]["artifact_root"] = str(tmp / "mlruns")
    cfg["ingest"]["batteries"] = list(batteries)
    cfg["ingest"]["min_discharge_cycles"] = 20
    cfg["split"] = {"train": list(batteries[:2]), "val": [batteries[2]], "test": [batteries[3]]}
    if n_models_small:
        cfg["train"]["models"] = {
            "linear_regression": {}, "ridge": {"alpha": 1.0},
            "random_forest": {"n_estimators": 20, "max_depth": 6, "n_jobs": 1},
            "gradient_boosting": {"n_estimators": 30, "max_depth": 2},
            "xgboost": {"n_estimators": 30, "max_depth": 3, "n_jobs": 1},
        }
    cfg["registry"]["model_name"] = "VoltGuard-Test"
    return cfg
