import joblib
import pandas as pd
import pytest

from src.features.engineering import FEATURE_COLUMNS
from src.models.evaluate import BUNDLE_NAME
from src.models.select import select_best
from src.utils.config import resolve


def test_selection_primary_metric():
    c = {"a": {"rmse": 2.0, "mae": 1.0, "r2": 0.9}, "b": {"rmse": 1.0, "mae": 5.0, "r2": 0.5}}
    assert select_best(c, tie_tolerance=0.0)[0] == "b"


def test_selection_tiebreak_uses_secondary():
    c = {"a": {"rmse": 1.000, "mae": 0.9, "r2": 0.9}, "b": {"rmse": 1.005, "mae": 0.5, "r2": 0.9}}
    assert select_best(c, tie_tolerance=0.01)[0] == "b"     # within 1 % -> lower MAE wins
    assert select_best(c, tie_tolerance=0.0)[0] == "a"


def test_selection_is_deterministic_and_validates():
    c = {"x": {"rmse": 1.0, "mae": 1.0, "r2": 0.5}, "y": {"rmse": 1.0, "mae": 1.0, "r2": 0.5}}
    assert select_best(c)[0] == select_best(dict(reversed(c.items())))[0] == "x"
    with pytest.raises(ValueError):
        select_best({})
    with pytest.raises(ValueError):
        select_best(c, primary="r2")


def test_bundle_predicts_expected_structure(pipeline_run, sample_payload):
    cfg, _ = pipeline_run
    b = joblib.load(resolve(cfg["paths"]["models_dir"]) / BUNDLE_NAME)
    assert b["features"] == FEATURE_COLUMNS and {"soh", "rul"} <= set(b["models"])
    X = b["preprocessor"].transform(pd.DataFrame([sample_payload])[b["features"]])
    assert b["models"]["soh"].predict(X).shape == (1,)


def test_all_candidates_tracked_in_mlflow(pipeline_run):
    import mlflow
    cfg, _ = pipeline_run
    mlflow.set_tracking_uri(cfg["mlflow"]["tracking_uri"])
    runs = mlflow.search_runs(experiment_names=[cfg["mlflow"]["experiment_name"]])
    exp = runs[runs["tags.stage"] == "experiment"]
    assert len(exp) == 2 * len(cfg["train"]["models"])
    for col in ("metrics.val_rmse", "metrics.val_mae", "metrics.val_r2", "metrics.training_time_s"):
        assert exp[col].notna().all()
