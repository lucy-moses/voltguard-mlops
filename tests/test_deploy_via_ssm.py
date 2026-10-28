from __future__ import annotations

import subprocess

import pytest

from scripts import deploy_via_ssm


@pytest.fixture
def deployment_environment():
    return {
        "AWS_REGION": "ap-south-1",
        "ECR_REGISTRY": "270068815292.dkr.ecr.ap-south-1.amazonaws.com",
        "ECR_REPOSITORY": "voltguard-api",
        "IMAGE_TAG": "a" * 40,
        "DVC_REMOTE_URL": "s3://voltguard-mlops-lucy-2026/voltguard",
        "EXPECTED_MODEL_VERSION": "2",
        "PRODUCTION_HTTPS_URL": "https://voltguard-api.duckdns.org",
    }


def test_remote_ssm_command_retrieves_secure_parameter_without_embedding_key(deployment_environment):
    command = deploy_via_ssm.build_remote_command(
        deployment_environment,
        "/voltguard/deploy/123456-1/api-key",
    )

    assert "aws ssm get-parameter" in command
    assert "--with-decryption" in command
    assert "/voltguard/deploy/123456-1/api-key" in command
    assert "API_KEY=" not in command
    assert "API_KEY_FILE" in command
    assert "X-API-Key" not in command


def test_remote_command_rejects_unscoped_parameter(deployment_environment):
    with pytest.raises(ValueError, match="under /voltguard/deploy/"):
        deploy_via_ssm.build_remote_command(deployment_environment, "/other/key")


def test_remote_command_requires_all_deployment_configuration(deployment_environment):
    deployment_environment.pop("ECR_REPOSITORY")
    with pytest.raises(ValueError, match="ECR_REPOSITORY"):
        deploy_via_ssm.build_remote_command(
            deployment_environment,
            "/voltguard/deploy/123456-1/api-key",
        )


def test_secure_parameter_matches_remote_api_key_env_file_format():
    assert deploy_via_ssm.build_secret_file_contents("safe-secret") == "API_KEY=safe-secret"
    with pytest.raises(ValueError, match="line break"):
        deploy_via_ssm.build_secret_file_contents("bad\nsecret")


def test_aws_cli_child_process_does_not_inherit_api_key(monkeypatch):
    monkeypatch.setenv("API_KEY", "do-not-inherit-this")
    observed = {}

    def fake_run(*args, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(deploy_via_ssm.subprocess, "run", fake_run)
    assert deploy_via_ssm._aws("sts", "get-caller-identity") == "ok"
    assert "API_KEY" not in observed["env"]
