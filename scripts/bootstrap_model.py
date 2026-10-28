"""Model bootstrap: fetch the versioned model artifact from the DVC remote, then verify it.

Runs at container start (before uvicorn) and can be run by hand.

Environment:
  ARTIFACT_DIR     where the model lives                       (default artifacts/models)
  MODEL_SOURCE     dvc   -> `dvc pull` the artifact (default)
                   local -> use files already present (local dev / docker-compose volume)
  MODEL_ALIAS      alias that must be present in manifest      (default champion)
  DVC_REMOTE_URL   optional override of the DVC remote URL, e.g. s3://my-bucket/voltguard
  AWS_REGION       optional region for S3
AWS credentials come from the environment or (on EC2) the instance IAM role - never from the image.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)-7s | bootstrap | %(message)s")
log = logging.getLogger("bootstrap")

BUNDLE_TARGETS = ("artifacts/models/manifest.json", "artifacts/models/voltguard_bundle.joblib")


def run(cmd: list[str], *, display_cmd: str | None = None) -> None:
    """Run bootstrap commands without logging remote URLs or raw CLI diagnostics."""
    shown = display_cmd or " ".join(cmd)
    log.info("$ %s", shown)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{shown} failed with exit code {exc.returncode}") from None


def dvc_pull() -> None:
    env_url = os.getenv("DVC_REMOTE_URL")
    if not Path(".git").exists():
        run(["dvc", "config", "--local", "core.no_scm", "true"])  # container has no git metadata
    if env_url:
        run(
            ["dvc", "remote", "modify", "--local", "storage", "url", env_url],
            display_cmd="dvc remote modify --local storage url <configured remote URL>",
        )
    if os.getenv("AWS_REGION"):
        run(["dvc", "remote", "modify", "--local", "storage", "region", os.environ["AWS_REGION"]])
    run(["dvc", "pull", "--quiet", "--force", *BUNDLE_TARGETS], display_cmd="dvc pull --force <locked model targets>")


def main() -> int:
    os.environ.setdefault("DVC_NO_ANALYTICS", "1")
    artifact_dir = Path(os.getenv("ARTIFACT_DIR", "artifacts/models"))
    source = os.getenv("MODEL_SOURCE", "dvc").lower()
    alias = os.getenv("MODEL_ALIAS", "champion")
    try:
        if source == "dvc":
            dvc_pull()
        elif source != "local":
            raise ValueError(f"MODEL_SOURCE must be 'dvc' or 'local', got {source!r}")
        from api.model_loader import ModelService  # verify exactly what the API will load
        svc = ModelService(artifact_dir, alias)
        svc.load()
        log.info("Model ready: %s v%s alias=%s", svc.manifest["model_name"], svc.manifest["model_version"], alias)
        print(json.dumps({"model": svc.manifest["model_name"], "version": svc.manifest["model_version"]}))
        return 0
    except Exception as exc:  # noqa: BLE001
        log.error("Bootstrap failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
