"""Central logging configuration."""
from __future__ import annotations

import logging
import os


def get_logger(name: str) -> logging.Logger:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        )
    return logging.getLogger(name)
