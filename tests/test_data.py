import numpy as np
import pandas as pd
import pytest

from src.data.clean import clean_cycles
from src.data.ingest import DataIngestionError, find_mat_file, parse_battery_file, run_ingestion
from src.data.validate import DataValidationError, validate_cycles
from tests.synthetic import make_test_config, write_synthetic_mat


def test_parse_mat_layout(tmp_path):
    write_synthetic_mat(tmp_path, ["B0005"], n_cycles=25)
    df = parse_battery_file(find_mat_file(tmp_path, "B0005"), "B0005")
    assert len(df) == 25 and df.cycle_number.tolist() == list(range(1, 26))
    assert df.charge_duration.notna().all() and (df.discharge_duration > 0).all()
    assert df.capacity.iloc[0] > df.capacity.iloc[-1]  # fade


def test_missing_file_raises_helpful_error(tmp_path):
    with pytest.raises(DataIngestionError, match="download_data|README"):
        find_mat_file(tmp_path, "B0005")


def test_too_few_cycles_rejected(tmp_path):
    cfg = make_test_config(tmp_path, batteries=("B0005", "B0006", "B0007", "B0018"))
    write_synthetic_mat(tmp_path / "raw_dir", cfg["ingest"]["batteries"], n_cycles=5)
    with pytest.raises(DataIngestionError):
        run_ingestion(cfg)


def _df(cfg, tmp_path):
    write_synthetic_mat(tmp_path / "raw_dir", cfg["ingest"]["batteries"], n_cycles=30)
    return pd.read_csv(run_ingestion(cfg))


def test_validation_and_cleaning(tmp_path):
    cfg = make_test_config(tmp_path)
    df = _df(cfg, tmp_path)
    assert validate_cycles(df, cfg)["n_batteries"] == 4
    bad = df.copy()
    bad.loc[0, "capacity"] = 99.0
    bad = pd.concat([bad, bad.iloc[[1]]])  # duplicate row
    cleaned = clean_cycles(bad, cfg)
    assert len(cleaned) == len(df) - 1 and cleaned.capacity.max() < 3.0


def test_validation_rejects_bad_schema(tmp_path):
    cfg = make_test_config(tmp_path)
    df = _df(cfg, tmp_path)
    with pytest.raises(DataValidationError):
        validate_cycles(df.drop(columns=["capacity"]), cfg)
    df2 = df.copy()
    df2["voltage_mean"] = np.nan
    with pytest.raises(DataValidationError):
        validate_cycles(df2, cfg)
