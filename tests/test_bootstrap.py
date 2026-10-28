import subprocess

import pytest

from scripts.bootstrap_model import run


def test_bootstrap_command_log_redacts_remote_url(monkeypatch, caplog):
    remote_url = "s3://private-audit-bucket/voltguard"
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)

    run(
        ["dvc", "remote", "modify", "--local", "storage", "url", remote_url],
        display_cmd="dvc remote modify --local storage url <configured remote URL>",
    )

    assert "configured remote URL" in caplog.text
    assert remote_url not in caplog.text


def test_bootstrap_command_error_does_not_echo_remote_url(monkeypatch, caplog):
    remote_url = "s3://private-audit-bucket/voltguard"
    cmd = ["dvc", "remote", "modify", "--local", "storage", "url", remote_url]

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="exit code 1") as exc:
        run(cmd, display_cmd="dvc remote modify --local storage url <configured remote URL>")

    assert remote_url not in caplog.text
    assert remote_url not in str(exc.value)
