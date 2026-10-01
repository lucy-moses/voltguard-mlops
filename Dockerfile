# VoltGuard API image. Contains code + dependencies + DVC pointers. It contains NO credentials
# and NO model weights: the model is pulled from the DVC remote at container start (entrypoint).
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 DVC_NO_ANALYTICS=1 \
    ARTIFACT_DIR=/app/artifacts/models MODEL_ALIAS=champion MODEL_SOURCE=dvc

# libgomp1 is required by xgboost / scikit-learn OpenMP; curl for HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-serve.txt .
RUN pip install -r requirements-serve.txt

# DVC pointers: which model version this image serves (dvc.lock) and where it lives (.dvc/config)
COPY .dvc/config .dvc/config
COPY .dvcignore dvc.yaml dvc.lock ./
COPY api ./api
COPY scripts/bootstrap_model.py ./scripts/bootstrap_model.py
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh && useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/artifacts/models && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
