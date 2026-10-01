"""Evaluate stage: apply the selection rule (validation), score the winner ONCE on test, build bundle."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import joblib
import pandas as pd

from mlflow.tracking import MlflowClient
from src.features.engineering import FEATURE_COLUMNS
from src.models.metrics import regression_metrics
from src.models.select import select_best
from src.utils.config import read_json, resolve, write_json
from src.utils.logging_utils import get_logger
from src.utils.mlflow_utils import setup_mlflow

log = get_logger(__name__)
BUNDLE_NAME = "voltguard_bundle.joblib"


def run_evaluate(cfg: dict[str, Any]) -> dict[str, Any]:
    metrics_dir = resolve(cfg["paths"]["metrics_dir"])
    models_dir = resolve(cfg["paths"]["models_dir"])
    train_metrics = read_json(metrics_dir / "train_metrics.json")
    test = pd.read_csv(resolve(cfg["paths"]["processed_dir"]) / "test.csv")
    pre = joblib.load(resolve(cfg["paths"]["preprocessors_dir"]) / "preprocessor.joblib")
    sel = cfg["selection"]
    setup_mlflow(cfg)
    client = MlflowClient()

    models: dict[str, Any] = {}
    report: dict[str, Any] = {"selection": {}, "test": {}}
    for target, cands in train_metrics.items():
        val_scores = {n: r["val"] for n, r in cands.items()}
        winner, why = select_best(val_scores, sel["primary_metric"], sel["secondary_metrics"], sel["tie_tolerance"])
        t = test[test[target].notna()]
        if t.empty:
            raise ValueError(f"No labelled test rows for target '{target}'")
        model = joblib.load(models_dir / "candidates" / cands[winner]["artifact"])
        scores = regression_metrics(t[target], model.predict(pre.transform(t[FEATURE_COLUMNS])))
        models[target] = model
        report["selection"][target] = {**why, "run_id": cands[winner]["run_id"], "val": cands[winner]["val"],
                                       "params": cands[winner]["params"]}
        report["test"][target] = scores
        for k, v in scores.items():  # attach held-out metrics to the winning experiment run
            client.log_metric(cands[winner]["run_id"], f"test_{k}", v)
        log.info("Selected %s -> %s | test RMSE=%.4f MAE=%.4f R2=%.4f", target, winner,
                 scores["rmse"], scores["mae"], scores["r2"])

    bundle = {
        "schema_version": 1,
        "features": FEATURE_COLUMNS,
        "preprocessor": pre,
        "models": models,
        "metadata": {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "selected_models": {t: report["selection"][t]["winner"] for t in models},
            "test_metrics": report["test"],
            "val_metrics": {t: report["selection"][t]["val"] for t in models},
            "eol_soh_percent": cfg["features"]["eol_soh_percent"],
            "nominal_capacity_ah": cfg["features"]["nominal_capacity_ah"],
            "seed": cfg["seed"],
        },
    }
    models_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, models_dir / BUNDLE_NAME)
    write_json(report, metrics_dir / "evaluation.json")
    return report
