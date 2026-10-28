"""Deployment guard tests; docker is always a shell mock and never the real client."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _bash_path() -> str:
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
            Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for the deployment guard tests")
    return bash


def _bash_style_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if os.name == "nt" and len(value) > 2 and value[1:3] == ":/":
        return f"/{value[0].lower()}{value[2:]}"
    return value


def _run_guard(
    body: str,
    *,
    ps_output: str = "",
    ps_exit: str = "0",
    inspect_output: str = "",
    inspect_exit: str = "0",
):
    library = Path(__file__).resolve().parents[1] / "scripts" / "deploy_guards.sh"
    env = os.environ.copy()
    env.update(
        {
            "DEPLOY_GUARDS": _bash_style_path(library),
            "PS_OUTPUT": ps_output,
            "PS_EXIT": ps_exit,
            "INSPECT_OUTPUT": inspect_output,
            "INSPECT_EXIT": inspect_exit,
        }
    )
    script = r"""
source "$DEPLOY_GUARDS"
docker() {
  case "$1" in
    ps) printf '%s' "$PS_OUTPUT"; return "$PS_EXIT" ;;
    inspect) printf '%s' "$INSPECT_OUTPUT"; return "$INSPECT_EXIT" ;;
    *) return 90 ;;
  esac
}
""" + body
    return subprocess.run(
        [_bash_path(), "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_container_lookup_successfully_confirms_absence():
    result = _run_guard(
        'NAME=voltguard-api; PREV_IMAGE=stale; PREV_CONTAINER_ID=stale; '
        'inspect_previous_container "$NAME" || exit 1; '
        'test -z "$PREV_IMAGE" && test -z "$PREV_CONTAINER_ID"'
    )
    assert result.returncode == 0


def test_container_listing_error_aborts():
    result = _run_guard(
        'NAME=voltguard-api; if inspect_previous_container "$NAME"; then exit 1; fi',
        ps_exit="17",
    )
    assert result.returncode == 0
    assert "Docker container listing failed" in result.stderr


def test_container_inspection_error_aborts_without_accepting_image():
    result = _run_guard(
        'NAME=voltguard-api; if inspect_previous_container "$NAME"; then exit 1; fi',
        ps_output="container-id",
        inspect_exit="19",
    )
    assert result.returncode == 0
    assert "Docker inspection failed" in result.stderr


def test_container_inspection_returns_previous_image():
    result = _run_guard(
        'NAME=voltguard-api; inspect_previous_container "$NAME" || exit 1; '
        'test "$PREV_CONTAINER_ID" = container-id && test "$PREV_IMAGE" = voltguard-api:old',
        ps_output="container-id",
        inspect_output="voltguard-api:old",
    )
    assert result.returncode == 0


def test_multiple_exact_name_results_abort():
    result = _run_guard(
        'NAME=voltguard-api; if inspect_previous_container "$NAME"; then exit 1; fi',
        ps_output="first-id\nsecond-id",
    )
    assert result.returncode == 0
    assert "multiple exact-name containers" in result.stderr


@pytest.mark.parametrize(("status", "expected"), [(2, 0), (3, 1), (0, 0), (91, 0)])
def test_public_failure_rollback_policy(status: int, expected: int):
    result = _run_guard(f"should_rollback_public_check {status}")
    assert result.returncode == expected
