import re

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.model_loader import ModelLoadError, ModelService
from api.schemas import BatteryFeatures
from src.features.engineering import FEATURE_COLUMNS
from src.utils.config import resolve


@pytest.fixture()
def client(pipeline_run):
    cfg, _ = pipeline_run
    svc = ModelService(resolve(cfg["paths"]["models_dir"]), "champion")
    svc.load()
    return TestClient(create_app(svc))


def test_schema_matches_feature_columns():
    assert list(BatteryFeatures.model_fields) == FEATURE_COLUMNS


def test_root_and_health(client):
    assert client.get("/").status_code == 200
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["model_loaded"] is True


def test_predict_returns_expected_structure(client, sample_payload):
    r = client.post("/predict", json=sample_payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"predicted_soh", "predicted_rul", "model_name", "model_version", "timestamp", "model_metadata"} <= set(body)
    assert 0 <= body["predicted_soh"] < 150 and body["predicted_rul"] >= 0
    assert body["model_version"] == "1" and body["model_alias"] == "champion"


def test_predict_without_optional_charge_duration(client, sample_payload):
    sample_payload.pop("charge_duration")
    assert client.post("/predict", json=sample_payload).status_code == 200


@pytest.mark.parametrize("patch", [
    {"voltage_mean": 9.0}, {"cycle_number": 0}, {"discharge_duration": -5}, {"unknown_field": 1},
    {"temperature_max": 10.0}, {"voltage_mean": "abc"}])
def test_predict_rejects_invalid_input(client, sample_payload, patch):
    assert client.post("/predict", json={**sample_payload, **patch}).status_code == 422


def test_predict_missing_field(client, sample_payload):
    sample_payload.pop("voltage_mean")
    assert client.post("/predict", json=sample_payload).status_code == 422


def test_model_info(client):
    r = client.get("/model-info")
    assert r.status_code == 200 and r.json()["model_version"] == "1" and r.json()["features"] == FEATURE_COLUMNS


def test_metrics_endpoint_tracks_requests(client, sample_payload):
    client.post("/predict", json=sample_payload)
    client.post("/predict", json={})
    text = client.get("/metrics").text
    for name in ("voltguard_http_requests_total", "voltguard_predictions_total",
                 "voltguard_http_request_duration_seconds", "voltguard_api_errors_total"):
        assert name in text
    assert re.search(r'voltguard_api_errors_total\{status="422"\} [1-9]', text)


def test_api_key_enforced_when_configured(client, sample_payload, monkeypatch):
    monkeypatch.setenv("API_KEY", "s3cret")
    assert client.post("/predict", json=sample_payload).status_code == 401
    assert client.post("/predict", json=sample_payload, headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post("/predict", json=sample_payload, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open for load balancers


def test_service_without_model_reports_503(tmp_path, sample_payload):
    svc = ModelService(tmp_path, "champion")
    c = TestClient(create_app(svc))
    assert c.get("/health").status_code == 503
    assert c.post("/predict", json=sample_payload).status_code == 503


def test_loader_rejects_wrong_alias_and_tampering(pipeline_run, tmp_path):
    import shutil
    cfg, _ = pipeline_run
    src = resolve(cfg["paths"]["models_dir"])
    for f in ("manifest.json", "voltguard_bundle.joblib"):
        shutil.copy(src / f, tmp_path / f)
    with pytest.raises(ModelLoadError, match="alias"):
        ModelService(tmp_path, "nonexistent").load()
    (tmp_path / "voltguard_bundle.joblib").write_bytes(b"corrupted")
    with pytest.raises(ModelLoadError, match="checksum"):
        ModelService(tmp_path, "champion").load()
    with pytest.raises(ModelLoadError, match="not found"):
        ModelService(tmp_path / "missing").load()
