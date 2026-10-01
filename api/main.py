"""VoltGuard prediction service (FastAPI)."""
from __future__ import annotations

import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from api.model_loader import ModelLoadError, ModelService
from api.schemas import BatteryFeatures, HealthResponse, PredictionResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
log = logging.getLogger("api")

REQUESTS = Counter("voltguard_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("voltguard_http_request_duration_seconds", "Request latency", ["path"])
PREDICTIONS = Counter("voltguard_predictions_total", "Successful predictions")
ERRORS = Counter("voltguard_api_errors_total", "API errors (HTTP >= 400)", ["status"])
MODEL_INFO = Gauge("voltguard_model_info", "Loaded model (value is always 1)", ["model_name", "model_version", "alias"])


def create_app(service: ModelService | None = None) -> FastAPI:
    preset = service is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not preset:
            app.state.service = ModelService()
            try:
                app.state.service.load()
            except ModelLoadError as exc:
                log.error("Model load failed: %s", exc)  # keep serving /health (503) for diagnostics
        svc: ModelService = app.state.service
        if svc.loaded:
            MODEL_INFO.labels(svc.manifest["model_name"], svc.manifest["model_version"], svc.alias).set(1)
        yield

    app = FastAPI(title="VoltGuard Battery SOH/RUL API", version="1.0.0", lifespan=lifespan)
    if preset:
        app.state.service = service

    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        expected = os.getenv("API_KEY")
        if expected and not (x_api_key and hmac.compare_digest(x_api_key, expected)):
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        start, status = time.perf_counter(), 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception:  # noqa: BLE001
            log.exception("Unhandled error")
            return JSONResponse({"detail": "Internal server error"}, status_code=500)
        finally:
            route = request.scope.get("route")
            path = route.path if route else "unmatched"
            REQUESTS.labels(request.method, path, str(status)).inc()
            LATENCY.labels(path).observe(time.perf_counter() - start)
            if status >= 400:
                ERRORS.labels(str(status)).inc()

    def svc() -> ModelService:
        s: ModelService = app.state.service
        if not s.loaded:
            raise HTTPException(status_code=503, detail="Model not loaded")
        return s

    @app.get("/")
    def root() -> dict:
        return {"service": "VoltGuard Battery SOH/RUL API", "docs": "/docs", "health": "/health"}

    @app.get("/health", response_model=HealthResponse)
    def health(response: Response) -> HealthResponse:
        s: ModelService = app.state.service
        if not s.loaded:
            response.status_code = 503
            return HealthResponse(status="model_not_loaded", model_loaded=False)
        return HealthResponse(status="ok", model_loaded=True, model_version=s.manifest["model_version"])

    @app.get("/model-info")
    def model_info() -> dict:
        return svc().info()

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/predict", response_model=PredictionResponse, dependencies=[Depends(require_api_key)])
    def predict(features: BatteryFeatures) -> PredictionResponse:
        s = svc()
        try:
            out = s.predict(features.model_dump())
        except Exception as exc:  # noqa: BLE001
            log.exception("Prediction failed")
            raise HTTPException(status_code=500, detail="Prediction failed") from exc
        PREDICTIONS.inc()
        m = s.manifest
        return PredictionResponse(
            **out, model_name=m["model_name"], model_version=str(m["model_version"]), model_alias=s.alias,
            timestamp=datetime.now(timezone.utc).isoformat(),
            model_metadata={"mlflow_run_id": m.get("run_id"), "selected_models": m.get("selected_models"),
                            "bundle_sha256": m.get("bundle_sha256"), "soh_unit": "percent", "rul_unit": "cycles"})

    return app


app = create_app()  # module-level ASGI app for uvicorn
