"""MLflow helpers."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import mlflow
from src.utils.config import resolve
from src.utils.logging_utils import get_logger

log = get_logger(__name__)


def setup_mlflow(cfg: dict[str, Any]) -> str:
    """Configure tracking URI and (idempotently) create the experiment."""
    uri = cfg["mlflow"]["tracking_uri"]
    if uri.startswith("sqlite:///"):
        db_path = uri[len("sqlite:///"):]
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    mlflow.set_tracking_uri(uri)
    name = cfg["mlflow"]["experiment_name"]
    if mlflow.get_experiment_by_name(name) is None:
        if uri.startswith("sqlite"):
            root = resolve(cfg["mlflow"]["artifact_root"])
            root.mkdir(parents=True, exist_ok=True)
            mlflow.create_experiment(name, artifact_location=root.as_uri())
        else:
            mlflow.create_experiment(name)
    mlflow.set_experiment(name)
    _restore_logging()
    log.info("MLflow tracking URI=%s experiment=%s", uri, name)
    return uri


def _restore_logging() -> None:
    """MLflow's alembic DB migration calls logging.fileConfig(), which disables existing loggers."""
    logging.getLogger().setLevel(os.getenv("LOG_LEVEL", "INFO"))
    for lname, lg in logging.root.manager.loggerDict.items():
        if isinstance(lg, logging.Logger) and lname.split(".")[0] in {"src", "api", "scripts"}:
            lg.disabled = False
