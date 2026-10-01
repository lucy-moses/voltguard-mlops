"""Configuration loading (params.yaml + configs/config.yaml + environment overrides)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_config(params_path: str = "params.yaml", config_path: str = "configs/config.yaml") -> dict[str, Any]:
    """Merge ML parameters and infrastructure config; apply env overrides."""
    cfg: dict[str, Any] = {}
    cfg.update(_read_yaml(ROOT / config_path))
    cfg.update(_read_yaml(ROOT / params_path))
    if os.getenv("MLFLOW_TRACKING_URI"):
        cfg["mlflow"]["tracking_uri"] = os.environ["MLFLOW_TRACKING_URI"]
    if os.getenv("MLFLOW_EXPERIMENT_NAME"):
        cfg["mlflow"]["experiment_name"] = os.environ["MLFLOW_EXPERIMENT_NAME"]
    return cfg


def resolve(path: str | Path) -> Path:
    """Resolve a config path relative to the repo root unless it is absolute."""
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def sha256_file(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def write_json(obj: Any, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True, default=str)


def read_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
