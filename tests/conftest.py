"""Shared fixtures. A session-scoped pipeline run on SYNTHETIC data feeds the model/API/pipeline tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.stages import run_all  # noqa: E402
from tests.synthetic import make_test_config, write_synthetic_mat  # noqa: E402


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("voltguard")
    cfg = make_test_config(tmp)
    write_synthetic_mat(Path(cfg["paths"]["raw_dir"]), cfg["ingest"]["batteries"])
    out = run_all(cfg)
    return cfg, out


@pytest.fixture()
def sample_payload() -> dict:
    return {"cycle_number": 60, "ambient_temperature": 24.0, "voltage_mean": 3.45, "voltage_std": 0.25,
            "voltage_min": 2.7, "voltage_range": 1.5, "current_mean": -2.0, "temperature_mean": 33.0,
            "temperature_max": 38.0, "temperature_rise": 8.0, "discharge_duration": 2500.0,
            "charge_duration": 9500.0}
