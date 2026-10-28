import hashlib
import json
import logging
from pathlib import Path

import pytest
import yaml

import mlflow
from scripts import verify_evaluation_artifacts as evaluation_guard
from scripts.validate_mlflow_tracking_uri import validate_tracking_uri
from scripts.validate_production_https_url import validate_production_https_url
from src.utils.mlflow_utils import setup_mlflow


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "http://api.example.invalid",
        "https://",
        "https:///health",
        "https://user:secret@api.example.invalid",
        "https://api.example.invalid?token=x",
        "https://api.example.invalid/#fragment",
        "https://api.example.invalid:bad",
        "https://api.example.invalid:",
        "https://api.example.invalid:65536",
        "https://api.example.invalid:444",
        "https://api.example.invalid/path",
        "https://api.example.invalid../",
        "https://other.example.invalid",
        "https://localhost",
        "https://127.0.0.1",
    ],
)
def test_production_https_url_rejects_invalid_or_unapproved_values(url):
    with pytest.raises(ValueError):
        validate_production_https_url(url, "api.example.invalid")


def test_production_https_url_requires_both_values():
    with pytest.raises(ValueError, match="must both be configured"):
        validate_production_https_url("https://api.example.invalid", None)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.example.invalid", "https://api.example.invalid"),
        ("https://api.example.invalid:443/", "https://api.example.invalid"),
        ("HTTPS://API.EXAMPLE.INVALID", "https://api.example.invalid"),
        ("https://api.example.invalid.", "https://api.example.invalid"),
        ("https://api.example.invalid:0443", "https://api.example.invalid"),
    ],
)
def test_production_https_url_normalizes_equivalent_approved_authorities(url, expected):
    assert validate_production_https_url(url, "API.EXAMPLE.INVALID") == expected


@pytest.mark.parametrize(
    ("uri", "host"),
    [
        (None, "mlflow.example.invalid"),
        ("sqlite:///mlflow.db", "mlflow.example.invalid"),
        ("file:///tmp/mlruns", "mlflow.example.invalid"),
        ("http://mlflow.example.invalid", "mlflow.example.invalid"),
        ("https://other.example.invalid", "mlflow.example.invalid"),
        ("https://127.0.0.1", "127.0.0.1"),
        ("https://user:password@mlflow.example.invalid", "mlflow.example.invalid"),
        ("https://mlflow.example.invalid/?token=secret", "mlflow.example.invalid"),
        ("https://mlflow.example.invalid", None),
        ("https://localhost", "localhost"),
    ],
)
def test_tracking_uri_rejects_unapproved_or_nonpersistent_locations(uri, host):
    with pytest.raises(ValueError):
        validate_tracking_uri(uri, host)


def test_tracking_uri_accepts_exact_approved_https_host():
    validate_tracking_uri("https://mlflow.example.invalid:8443/team", "mlflow.example.invalid:8443")


def test_tracking_uri_requires_authentication_variables_as_a_pair():
    with pytest.raises(ValueError, match="Configure both"):
        validate_tracking_uri("https://mlflow.example.invalid", "mlflow.example.invalid", "user", None)


def test_mlflow_setup_logs_uri_scheme_without_uri_contents(monkeypatch, caplog):
    uri = "https://user:private@mlflow.example.invalid/team?token=private"
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda value: None)
    monkeypatch.setattr(mlflow, "get_experiment_by_name", lambda value: object())
    monkeypatch.setattr(mlflow, "set_experiment", lambda value: None)
    config = {"mlflow": {"tracking_uri": uri, "experiment_name": "audit-test"}}

    with caplog.at_level(logging.INFO, logger="src.utils.mlflow_utils"):
        setup_mlflow(config)

    assert uri not in caplog.text
    assert "scheme=https" in caplog.text


def _make_evaluation_release(tmp_path):
    metrics_path = tmp_path / evaluation_guard.EVALUATION_PATH
    bundle_path = tmp_path / evaluation_guard.BUNDLE_PATH
    metrics_path.parent.mkdir(parents=True)
    bundle_path.parent.mkdir(parents=True)
    metrics_path.write_text(
        json.dumps(
            {
                "test": {
                    "soh": {"rmse": 0.4, "mae": 0.3, "r2": 0.9},
                    "rul": {"rmse": 13.0, "mae": 12.0, "r2": 0.7},
                }
            }
        ),
        encoding="utf-8",
    )
    bundle_path.write_bytes(b"isolated synthetic bundle")
    lock_path = tmp_path / "dvc.lock"
    lock_path.write_text(
        yaml.safe_dump(
            {
                "stages": {
                    "evaluate": {
                        "outs": [
                            {"path": evaluation_guard.EVALUATION_PATH, "md5": hashlib.md5(metrics_path.read_bytes()).hexdigest()},
                            {"path": evaluation_guard.BUNDLE_PATH, "md5": hashlib.md5(bundle_path.read_bytes()).hexdigest()},
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_evaluation_guard_accepts_locked_metrics_and_bundle(tmp_path):
    _make_evaluation_release(tmp_path)
    evaluation_guard.verify_evaluation_artifacts(tmp_path)


def test_evaluation_guard_rejects_bundle_hash_mismatch(tmp_path):
    _make_evaluation_release(tmp_path)
    bundle_path = tmp_path / evaluation_guard.BUNDLE_PATH
    bundle_path.write_bytes(b"changed bundle")
    with pytest.raises(ValueError, match="DVC hash mismatch"):
        evaluation_guard.verify_evaluation_artifacts(tmp_path)


def test_evaluation_guard_rejects_incomplete_metrics(tmp_path):
    _make_evaluation_release(tmp_path)
    metrics_path = tmp_path / evaluation_guard.EVALUATION_PATH
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    del metrics["test"]["soh"]["rmse"]
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    lock = yaml.safe_load((tmp_path / "dvc.lock").read_text(encoding="utf-8"))
    lock["stages"]["evaluate"]["outs"][0]["md5"] = hashlib.md5(metrics_path.read_bytes()).hexdigest()
    (tmp_path / "dvc.lock").write_text(yaml.safe_dump(lock), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete or invalid"):
        evaluation_guard.verify_evaluation_artifacts(tmp_path)


def test_cd_release_preflight_uses_production_environment_scope():
    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/cd.yml").read_text(encoding="utf-8"))
    assert workflow["jobs"]["release-preflight"]["environment"] == "production"
