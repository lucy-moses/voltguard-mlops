"""Fail closed unless registration targets the explicitly approved HTTPS MLflow host."""
from __future__ import annotations

import ipaddress
import os
import sys
from urllib.parse import urlsplit


def _authority(uri: str) -> tuple[str, int | None]:
    parsed = urlsplit(uri)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("MLFLOW_TRACKING_URI must be an HTTPS tracking-server URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(
            "Do not embed credentials in MLFLOW_TRACKING_URI; use MLflow's separate authentication variables."
        )
    if parsed.query or parsed.fragment:
        raise ValueError("MLFLOW_TRACKING_URI must not contain query strings or fragments.")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("MLFLOW_TRACKING_URI must identify a remote persistent server, not localhost.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and address.is_loopback:
        raise ValueError("MLFLOW_TRACKING_URI must identify a remote persistent server, not a loopback address.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("MLFLOW_TRACKING_URI has an invalid port.") from exc
    return hostname, None if port == 443 else port


def validate_tracking_uri(
    uri: str | None,
    approved_host: str | None,
    username: str | None = None,
    password: str | None = None,
) -> None:
    if bool(username) != bool(password):
        raise ValueError("Configure both MLFLOW_TRACKING_USERNAME and MLFLOW_TRACKING_PASSWORD, or neither.")
    if not uri or not uri.strip():
        raise ValueError(
            "MLFLOW_TRACKING_URI is required when evaluation stages change. Configure a persistent "
            "HTTPS MLflow tracking server before retraining or registration."
        )
    if not approved_host or not approved_host.strip():
        raise ValueError(
            "The MLFLOW_TRACKING_ALLOWED_HOST repository variable is required for registration. "
            "Set it to the approved server host (and port, if non-default) after verifying persistence."
        )

    actual = _authority(uri.strip())
    allowed_text = approved_host.strip()
    if "://" in allowed_text or any(char in allowed_text for char in "/?#@"):
        raise ValueError("MLFLOW_TRACKING_ALLOWED_HOST must contain only the approved host and optional port.")
    allowed = _authority(f"https://{allowed_text}")
    if actual != allowed:
        raise ValueError("MLFLOW_TRACKING_URI host does not match MLFLOW_TRACKING_ALLOWED_HOST.")


def main() -> int:
    try:
        validate_tracking_uri(
            os.environ.get("MLFLOW_TRACKING_URI"),
            os.environ.get("MLFLOW_TRACKING_ALLOWED_HOST"),
            os.environ.get("MLFLOW_TRACKING_USERNAME"),
            os.environ.get("MLFLOW_TRACKING_PASSWORD"),
        )
    except ValueError as exc:
        print(f"MLflow registration blocked: {exc}", file=sys.stderr)
        return 1
    print("Approved HTTPS MLflow host configuration validated; no server connection was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
