"""Loads the versioned model bundle described by manifest.json (retrieved from the DVC remote by
scripts/bootstrap_model.py). No model filename is hard-coded: the manifest names the bundle and its
SHA-256, and the configured alias (default `champion`) must be present in the manifest."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

log = logging.getLogger("api.model_loader")
MANIFEST = "manifest.json"


class ModelLoadError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


class ModelService:
    def __init__(self, artifact_dir: str | Path | None = None, alias: str | None = None) -> None:
        self.artifact_dir = Path(artifact_dir or os.getenv("ARTIFACT_DIR", "artifacts/models"))
        self.alias = alias or os.getenv("MODEL_ALIAS", "champion")
        self.manifest: dict[str, Any] = {}
        self.bundle: dict[str, Any] | None = None

    @property
    def loaded(self) -> bool:
        return self.bundle is not None

    def load(self) -> None:
        import json
        mpath = self.artifact_dir / MANIFEST
        if not mpath.exists():
            raise ModelLoadError(f"{mpath} not found - run scripts/bootstrap_model.py first")
        manifest = json.loads(mpath.read_text())
        if self.alias not in manifest.get("aliases", []):
            raise ModelLoadError(
                f"Manifest v{manifest.get('model_version')} has aliases {manifest.get('aliases')}, "
                f"but MODEL_ALIAS={self.alias!r} is required. Refusing to serve.")
        bpath = self.artifact_dir / manifest["bundle_file"]
        if not bpath.exists():
            raise ModelLoadError(f"Bundle {bpath} missing")
        if _sha256(bpath) != manifest["bundle_sha256"]:
            raise ModelLoadError("Bundle checksum mismatch - artifact corrupted or not the registered one")
        try:
            bundle = joblib.load(bpath)
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadError(f"Cannot deserialise bundle: {exc}") from exc
        if "soh" not in bundle.get("models", {}):
            raise ModelLoadError("Bundle has no SOH model")
        self.manifest, self.bundle = manifest, bundle
        log.info("Loaded %s v%s (alias=%s)", manifest["model_name"], manifest["model_version"], self.alias)

    def predict(self, record: dict[str, Any]) -> dict[str, float | None]:
        if self.bundle is None:
            raise ModelLoadError("Model not loaded")
        b = self.bundle
        df = pd.DataFrame([record]).reindex(columns=b["features"])  # missing optional -> NaN -> imputed
        X = b["preprocessor"].transform(df)
        soh = float(b["models"]["soh"].predict(X)[0])
        rul = float(b["models"]["rul"].predict(X)[0]) if "rul" in b["models"] else None
        return {"predicted_soh": max(0.0, soh), "predicted_rul": None if rul is None else max(0.0, rul)}

    def info(self) -> dict[str, Any]:
        m = self.manifest
        return {
            "model_name": m.get("model_name"), "model_version": m.get("model_version"),
            "alias": self.alias, "aliases_in_manifest": m.get("aliases"),
            "mlflow_run_id": m.get("run_id"), "registered_at": m.get("registered_at"),
            "bundle_sha256": m.get("bundle_sha256"), "features": m.get("features"),
            "selected_models": m.get("selected_models"), "metrics": m.get("metrics"),
            "bundle_metadata": (self.bundle or {}).get("metadata"),
        }
