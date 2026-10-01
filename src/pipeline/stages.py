"""DVC stage entry points:  python -m src.pipeline.stages <stage>"""
from __future__ import annotations

import sys
from typing import Any

from src.data.ingest import run_ingestion
from src.models.evaluate import run_evaluate
from src.models.registry import run_register
from src.models.train import run_train
from src.pipeline.preprocess import run_preprocess
from src.utils.config import load_config
from src.utils.logging_utils import get_logger

log = get_logger(__name__)

STAGES = {
    "data_ingestion": run_ingestion,
    "preprocess": run_preprocess,
    "train": run_train,
    "evaluate": run_evaluate,
    "register_model": run_register,
}


def run_all(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run every stage in order (used by tests and the smoke script)."""
    out: dict[str, Any] = {}
    for name, fn in STAGES.items():
        log.info("=== stage: %s ===", name)
        out[name] = fn(cfg)
    return out


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1 or args[0] not in STAGES:
        print(f"usage: python -m src.pipeline.stages [{'|'.join(STAGES)}]", file=sys.stderr)
        return 2
    STAGES[args[0]](load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
