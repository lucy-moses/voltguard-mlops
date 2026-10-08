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


def main() -> int:
    manifest_bytes = MANIFEST_PATH.read_bytes()
    manifest = json.loads(manifest_bytes)
    lock = yaml.safe_load(LOCK_PATH.read_text(encoding="utf-8"))

    lock_outputs = lock["stages"]["register_model"]["outs"]
    lock_manifest = next(out for out in lock_outputs if out["path"] == "artifacts/models/manifest.json")
    actual_md5 = hashlib.md5(manifest_bytes).hexdigest()
    if lock_manifest["md5"] != actual_md5:
        raise SystemExit(
            f"Manifest hash mismatch: dvc.lock={lock_manifest['md5']} file={actual_md5}"
        )

    if manifest.get("promoted") is not True or "champion" not in manifest.get("aliases", []):
        raise SystemExit("Deployment manifest is not a promoted champion; refusing release")

    bundle_path = (MODEL_DIR / manifest["bundle_file"]).resolve()
    if MODEL_DIR.resolve() not in bundle_path.parents:
        raise SystemExit("Manifest bundle_file escapes artifacts/models; refusing release")
    bundle_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if bundle_hash != manifest["bundle_sha256"]:
        raise SystemExit(
            f"Bundle checksum mismatch: manifest={manifest['bundle_sha256']} file={bundle_hash}"
        )

    print(
        "Verified deployment release: "
        f"{manifest['model_name']} v{manifest['model_version']} "
        f"aliases={','.join(manifest['aliases'])} dvc_md5={actual_md5}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
