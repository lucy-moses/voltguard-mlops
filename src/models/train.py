"""Training stage: train every candidate model for each target and track it in MLflow."""
from __future__ import annotations

import time
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge

import mlflow
from src.features.engineering import FEATURE_COLUMNS
from src.models.metrics import regression_metrics
from src.utils.config import resolve, write_json
from src.utils.logging_utils import get_logger
from src.utils.mlflow_utils import setup_mlflow

log = get_logger(__name__)
TARGETS = ("soh", "rul")


def build_model(name: str, params: dict[str, Any], seed: int):
    if name == "linear_regression":
        return LinearRegression(**params)
    if name == "ridge":
        return Ridge(**params)
    if name == "random_forest":
        return RandomForestRegressor(random_state=seed, **params)
    if name == "gradient_boosting":
        return GradientBoostingRegressor(random_state=seed, **params)
    if name == "xgboost":
        from xgboost import XGBRegressor
        return XGBRegressor(random_state=seed, **params)
    raise ValueError(f"Unknown model '{name}'")


def feature_importance(model, features: list[str]) -> dict[str, float] | None:
    if hasattr(model, "feature_importances_"):
        vals = model.feature_importances_
    elif hasattr(model, "coef_"):
        vals = np.abs(np.ravel(model.coef_))  # |standardised coefficient|
    else:
        return None
    return {f: float(v) for f, v in zip(features, vals)}


def run_train(cfg: dict[str, Any]) -> dict[str, Any]:
    seed = int(cfg["seed"])
    np.random.seed(seed)
    proc = resolve(cfg["paths"]["processed_dir"])
    train, val = pd.read_csv(proc / "train.csv"), pd.read_csv(proc / "val.csv")
    pre = joblib.load(resolve(cfg["paths"]["preprocessors_dir"]) / "preprocessor.joblib")
    setup_mlflow(cfg)
    cand_dir = resolve(cfg["paths"]["models_dir"]) / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, Any]] = {}
    for target in TARGETS:
        tr, va = train[train[target].notna()], val[val[target].notna()]
        if tr.empty or va.empty:
            log.warning("Target '%s' has no labelled rows in train/val - skipped", target)
            continue
        Xtr, Xva = pre.transform(tr[FEATURE_COLUMNS]), pre.transform(va[FEATURE_COLUMNS])
        results[target] = {}
        for name, params in cfg["train"]["models"].items():
            with mlflow.start_run(run_name=f"{target}-{name}") as run:
                mlflow.set_tags({"target": target, "model_type": name, "stage": "experiment"})
                mlflow.log_params({f"{k}": v for k, v in params.items()})
                mlflow.log_param("seed", seed)
                mlflow.log_param("n_features", len(FEATURE_COLUMNS))
                model = build_model(name, params, seed)
                t0 = time.perf_counter()
                model.fit(Xtr, tr[target])
                elapsed = time.perf_counter() - t0
                m_tr = regression_metrics(tr[target], model.predict(Xtr))
                m_va = regression_metrics(va[target], model.predict(Xva))
                mlflow.log_metric("training_time_s", elapsed)
                mlflow.log_metrics({f"train_{k}": v for k, v in m_tr.items()})
                mlflow.log_metrics({f"val_{k}": v for k, v in m_va.items()})
                imp = feature_importance(model, FEATURE_COLUMNS)
                if imp:
                    mlflow.log_dict(imp, "feature_importance.json")
                path = cand_dir / f"{target}_{name}.joblib"
                joblib.dump(model, path)
                mlflow.log_artifact(str(path), artifact_path="model")
                results[target][name] = {
                    "run_id": run.info.run_id, "params": params, "training_time_s": elapsed,
                    "train": m_tr, "val": m_va, "artifact": str(path.name),
                }
                log.info("%s/%-18s val RMSE=%.4f MAE=%.4f R2=%.4f (%.2fs)",
                         target, name, m_va["rmse"], m_va["mae"], m_va["r2"], elapsed)
    if not results:
        raise RuntimeError("No target could be trained (no labelled rows)")
    write_json(results, resolve(cfg["paths"]["metrics_dir"]) / "train_metrics.json")
    return results
