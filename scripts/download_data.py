"""Download the NASA PCoE Li-ion battery aging dataset into data/raw (recursively unzips).

    python scripts/download_data.py [--url URL] [--dest data/raw]

If the automatic download fails (the URL may move), follow the manual instructions in data/README.md.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.utils.config import load_config, resolve  # noqa: E402
from src.utils.logging_utils import get_logger  # noqa: E402

log = get_logger("download_data")


def unzip_recursive(zpath: Path, dest: Path) -> None:
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(dest)
    for nested in list(dest.rglob("*.zip")):
        unzip_recursive(nested, nested.parent)
        nested.unlink()


def main() -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=cfg["dataset"]["url"])
    ap.add_argument("--dest", default=cfg["paths"]["raw_dir"])
    args = ap.parse_args()
    dest = resolve(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "nasa.zip"
            log.info("Downloading %s", args.url)
            with urllib.request.urlopen(args.url, timeout=120) as r, open(zpath, "wb") as fh:
                shutil.copyfileobj(r, fh)
            unzip_recursive(zpath, dest)
    except Exception as exc:  # noqa: BLE001
        log.error("Automatic download failed: %s\nFollow the manual steps in data/README.md.", exc)
        return 1
    found = sorted(p.name for p in dest.rglob("B00*.mat"))
    log.info("Found %d battery files: %s", len(found), found)
    needed = {f"{b}.mat" for b in cfg["ingest"]["batteries"]}
    missing = needed - set(found)
    if missing:
        log.error("Missing expected files: %s", sorted(missing))
        return 1
    log.info("Next: `dvc add data/raw && git add data/raw.dvc data/.gitignore`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
