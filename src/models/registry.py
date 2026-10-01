"""Register stage: log bundle as MLflow pyfunc model, register version, manage aliases.

Aliases:
- candidate -> newest version
- champion -> promoted version when the new model beats the current champion

The manifest is the bridge between MLflow and deployment.
"""

from __future__ import annotations

import os
import shutil
import stat
import time
from datetime import datetime, timezone
from typing import Any

import mlflow
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient
from src.models.evaluate import BUNDLE_NAME
from src.models.pyfunc_model import VoltGuardPyfunc
from src.utils.config import ROOT, read_json, resolve, sha256_file, write_json
from src.utils.logging_utils import get_logger
from src.utils.mlflow_utils import setup_mlflow

log = get_logger(__name__)

MANIFEST_NAME = "manifest.json"


# ---------------------------------------------------------------------
# Windows-safe cleanup for MLflow 2.16.2
# ---------------------------------------------------------------------
if os.name == "nt":
    # Windows: files copied out of a Git-tracked src/ folder (or touched by
    # pip/mlflow) sometimes end up with the read-only attribute set, which makes
    # shutil.rmtree fail with PermissionError no matter how many times you retry
    # the same call. Fix: on each failure, clear the read-only bit on the
    # offending path and retry the delete - this is the standard Windows fix,
    # not a timing issue.
    _original_rmtree = shutil.rmtree

    def _clear_readonly_and_retry(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass  # last resort below will catch anything still stuck

    def _rmtree_windows_safe(path, ignore_errors=False, onerror=None):
        try:
            _original_rmtree(path, onerror=_clear_readonly_and_retry)
            return
        except Exception:
            pass
        # Still stuck (rare): short retry loop for genuine transient locks, then give up quietly.
        for delay in (0.2, 0.5, 1.0, 2.0):
            time.sleep(delay)
            try:
                _original_rmtree(path, onerror=_clear_readonly_and_retry)
                return
            except Exception:
                continue
        # Never crash the pipeline over a throwaway temp folder.
        try:
            _original_rmtree(path, ignore_errors=True)
        except Exception:
            pass

    shutil.rmtree = _rmtree_windows_safe


def _flat_metrics(report: dict[str, Any]) -> dict[str, float]:
    """Flatten evaluation metrics into a single dictionary."""

    test_metrics = {
        f"{target}_test_{metric}": value
        for target, metrics in report["test"].items()
        for metric, value in metrics.items()
    }

    validation_metrics = {
        f"{target}_val_{metric}": value
        for target, details in report["selection"].items()
        for metric, value in details["val"].items()
    }

    return test_metrics | validation_metrics


def run_register(cfg: dict[str, Any]) -> dict[str, Any]:
    """Register the VoltGuard model bundle with MLflow."""

    models_dir = resolve(cfg["paths"]["models_dir"])

    bundle_path = models_dir / BUNDLE_NAME

    metrics_dir = resolve(cfg["paths"]["metrics_dir"])

    report = read_json(
        metrics_dir / "evaluation.json"
    )

    reg = cfg["registry"]

    name = reg["model_name"]

    setup_mlflow(cfg)

    client = MlflowClient()

    flat = _flat_metrics(report)

    # Example:
    # soh_test_rmse
    # rul_test_rmse
    pm = reg["promotion_metric"]

    # ---------------------------------------------------------------
    # Start MLflow registration run
    # ---------------------------------------------------------------

    with mlflow.start_run(
        run_name="register-voltguard-bundle"
    ) as run:

        mlflow.set_tag(
            "stage",
            "registration",
        )

        for target, selection in report["selection"].items():

            mlflow.set_tag(
                f"{target}_source_run_id",
                selection["run_id"],
            )

            mlflow.set_tag(
                f"{target}_model_type",
                selection["winner"],
            )

        mlflow.log_metrics(flat)

        # -----------------------------------------------------------
        # Log custom PyFunc model
        # -----------------------------------------------------------

        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=VoltGuardPyfunc(),
            artifacts={
                "bundle": str(bundle_path),
            },
            code_paths=[
                str(ROOT / "src"),
            ],
            pip_requirements=[
                "numpy",
                "pandas",
                "scikit-learn",
                "xgboost",
                "joblib",
                "mlflow",
            ],
        )

        run_id = run.info.run_id

    # ---------------------------------------------------------------
    # Register model
    # ---------------------------------------------------------------

    model_uri = f"runs:/{run_id}/model"

    version = mlflow.register_model(
        model_uri,
        name,
    )

    version_number = str(version.version)

    # ---------------------------------------------------------------
    # Add model-version metrics
    # ---------------------------------------------------------------

    for metric_name, value in flat.items():

        client.set_model_version_tag(
            name,
            version_number,
            metric_name,
            str(value),
        )

    # Newest version is always candidate.
    client.set_registered_model_alias(
        name,
        "candidate",
        version_number,
    )

    # ---------------------------------------------------------------
    # Find current champion
    # ---------------------------------------------------------------

    try:

        champion = client.get_model_version_by_alias(
            name,
            "champion",
        )

        champion_score = float(
            champion.tags.get(
                pm,
                "inf",
            )
        )

    except MlflowException:

        champion = None
        champion_score = float("inf")

    # ---------------------------------------------------------------
    # Promotion logic
    # ---------------------------------------------------------------

    new_score = float(
        flat[pm]
    )

    min_relative_improvement = float(
        reg["min_relative_improvement"]
    )

    promoted = (
        champion is None
        or new_score
        < champion_score
        * (1 - min_relative_improvement)
    )

    if promoted:

        client.set_registered_model_alias(
            name,
            "champion",
            version_number,
        )

    log.info(
        "Registered %s v%s | %s=%.4f vs champion=%s -> promoted=%s",
        name,
        version_number,
        pm,
        new_score,
        champion_score if champion else "none",
        promoted,
    )

    # ---------------------------------------------------------------
    # Deployment manifest
    # ---------------------------------------------------------------

    manifest = {
        "model_name": name,
        "model_version": version_number,
        "run_id": run_id,

        "aliases": (
            ["candidate", "champion"]
            if promoted
            else ["candidate"]
        ),

        "promoted": promoted,

        "previous_champion_version": (
            str(champion.version)
            if champion
            else None
        ),

        "bundle_file": BUNDLE_NAME,

        "bundle_sha256": sha256_file(
            bundle_path
        ),

        "features": read_json(
            metrics_dir / "preprocess_report.json"
        )["features"],

        "metrics": flat,

        "selected_models": {
            target: selection["winner"]
            for target, selection
            in report["selection"].items()
        },

        "registered_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }

    write_json(
        manifest,
        models_dir / MANIFEST_NAME,
    )

    return manifest
