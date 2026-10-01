import numpy as np
import pandas as pd
import pytest

from src.features.engineering import FEATURE_COLUMNS, FORBIDDEN_FEATURES, add_targets, build_features, split_by_battery
from src.utils.config import load_config


def _frame():
    n = 100
    return pd.DataFrame({
        "battery_id": ["A"] * n + ["B"] * n, "cycle_number": list(range(1, n + 1)) * 2,
        "voltage_max": 4.2, "voltage_min": 2.7, "temperature_max": 40.0, "temperature_min": 30.0,
        "capacity": list(np.linspace(2.0, 1.2, n)) + list(np.linspace(2.0, 1.6, n))})


def test_no_target_leakage_in_feature_list():
    assert not set(FEATURE_COLUMNS) & FORBIDDEN_FEATURES


def test_derived_features():
    out = build_features(_frame())
    assert np.allclose(out.voltage_range, 1.5) and np.allclose(out.temperature_rise, 10.0)


def test_targets_soh_and_rul():
    cfg = load_config()
    out = add_targets(_frame(), cfg)
    a = out[out.battery_id == "A"]
    assert a.soh.iloc[0] == pytest.approx(100.0)
    eol_cycle = a[a.soh <= cfg["features"]["eol_soh_percent"]].cycle_number.min()
    assert a[a.cycle_number == eol_cycle].rul.iloc[0] == 0
    assert a.rul.iloc[0] == eol_cycle - 1 and (a.rul.dropna() >= 0).all()
    assert out[out.battery_id == "B"].rul.isna().all()  # never reaches EOL -> censored, not invented


def test_split_is_by_battery_and_disjoint():
    cfg = load_config()
    df = pd.DataFrame({"battery_id": ["B0005", "B0006", "B0007", "B0018"] * 3, "x": range(12)})
    parts = split_by_battery(df, cfg)
    ids = [set(p.battery_id) for p in parts.values()]
    assert ids[0].isdisjoint(ids[1]) and ids[0].isdisjoint(ids[2]) and ids[1].isdisjoint(ids[2])
    cfg["split"]["val"] = ["B0005"]  # overlap with train
    with pytest.raises(ValueError):
        split_by_battery(df, cfg)
