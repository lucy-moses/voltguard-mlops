"""Fail closed if the manifest, DVC lock, and model bundle do not describe one release."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "artifacts" / "models"
MANIFEST_PATH = MODEL_DIR / "manifest.json"
LOCK_PATH = ROOT / "dvc.lock"
PIPELINE_PATH = ROOT / "dvc.yaml"
PARAMS_PATH = ROOT / "params.yaml"


def md5_file(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def main() -> int:
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_bytes)
    lock = yaml.safe_load(LOCK_PATH.read_text(encoding="utf-8"))
    pipeline = yaml.safe_load(PIPELINE_PATH.read_text(encoding="utf-8"))
    params = yaml.safe_load(PARAMS_PATH.read_text(encoding="utf-8"))

    lock_stage = lock["stages"]["register_model"]
    pipeline_stage = pipeline["stages"]["register_model"]
    if lock_stage.get("cmd") != pipeline_stage["cmd"]:
        raise SystemExit("register_model command differs from dvc.lock; refusing to reuse release")

    locked_registry_params = lock_stage.get("params", {}).get("params.yaml", {}).get("registry")
    if locked_registry_params != params.get("registry"):
        raise SystemExit("registry parameters differ from dvc.lock; refusing to reuse release")

    # A valid manifest alone is insufficient if the registration code, evaluation,
    # or model bundle changed. Verify every input that DVC locked for registration.
    for dep in lock_stage.get("deps", []):
        dep_path = (ROOT / dep["path"]).resolve()
        if ROOT.resolve() not in dep_path.parents:
            raise SystemExit(f"Locked registration dependency escapes repository: {dep['path']}")
        if not dep_path.is_file():
            raise SystemExit(f"Locked registration dependency is missing: {dep['path']}")
        expected = dep.get("md5")
        actual = md5_file(dep_path)
        if expected != actual:
            raise SystemExit(
                f"Registration dependency hash mismatch for {dep['path']}: "
                f"dvc.lock={expected} file={actual}"
            )

    lock_outputs = lock_stage["outs"]
    lock_manifest = next(out for out in lock_outputs if out["path"] == "artifacts/models/manifest.json")
    lock_bundle = next(
        out
        for out in lock["stages"]["evaluate"]["outs"]
        if out["path"] == "artifacts/models/voltguard_bundle.joblib"
    )
    actual_md5 = md5_file(MANIFEST_PATH)
    if lock_manifest["md5"] != actual_md5:
        raise SystemExit(
            f"Manifest hash mismatch: dvc.lock={lock_manifest['md5']} file={actual_md5}"
        )

    if manifest.get("promoted") is not True or "champion" not in manifest.get("aliases", []):
        raise SystemExit("Deployment manifest is not a promoted champion; refusing release")

    bundle_path = (MODEL_DIR / manifest["bundle_file"]).resolve()
    if MODEL_DIR.resolve() not in bundle_path.parents:
        raise SystemExit("Manifest bundle_file escapes artifacts/models; refusing release")
    if bundle_path.relative_to(ROOT).as_posix() != lock_bundle["path"]:
        raise SystemExit("Manifest bundle differs from the bundle pinned by dvc.lock; refusing release")
    bundle_md5 = md5_file(bundle_path)
    if lock_bundle["md5"] != bundle_md5:
        raise SystemExit(
            f"Bundle DVC hash mismatch: dvc.lock={lock_bundle['md5']} file={bundle_md5}"
        )
    bundle_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if bundle_hash != manifest["bundle_sha256"]:
        raise SystemExit(
            f"Bundle checksum mismatch: manifest={manifest['bundle_sha256']} file={bundle_hash}"
        )

    print(
        "Verified locked deployment release and registration inputs: "
        f"{manifest['model_name']} v{manifest['model_version']} "
        f"aliases={','.join(manifest['aliases'])} dvc_md5={actual_md5}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
