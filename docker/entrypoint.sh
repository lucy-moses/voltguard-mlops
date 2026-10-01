#!/bin/sh
# 1) fetch + verify model from DVC remote  2) start FastAPI
set -eu
python scripts/bootstrap_model.py
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${UVICORN_WORKERS:-1}"
