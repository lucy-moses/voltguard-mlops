"""Validate the configured public HTTPS ingress without making a network request."""

from __future__ import annotations

import ipaddress
import os
import re
import sys
from urllib.parse import urlsplit

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


def _normalize_hostname(hostname: str) -> str:
    try:
        normalized = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("hostname is malformed") from exc
    if normalized.endswith("."):
        normalized = normalized[:-1]
    if not normalized or len(normalized) > 253 or any(not _DNS_LABEL.fullmatch(label) for label in normalized.split(".")):
        raise ValueError("hostname is malformed")
    if "." not in normalized or normalized == "localhost" or normalized.endswith(".localhost"):
        raise ValueError("hostname must be a fully qualified production DNS name")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        raise ValueError("production ingress must use an approved DNS hostname, not an IP address")
    return normalized


def validate_production_https_url(url: str | None, approved_hostname: str | None) -> str:
    """Require an HTTPS origin whose DNS hostname exactly matches the approved host."""
    if not url or not approved_hostname:
        raise ValueError("PRODUCTION_HTTPS_URL and PRODUCTION_HTTPS_HOST must both be configured")
    if url != url.strip() or any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError("PRODUCTION_HTTPS_URL contains whitespace or control characters")
    if any(character in url for character in "?#"):
        raise ValueError("PRODUCTION_HTTPS_URL must not contain a query string or fragment")

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port  # Access validates malformed and out-of-range ports.
    except ValueError as exc:
        raise ValueError("PRODUCTION_HTTPS_URL is malformed") from exc

    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError("PRODUCTION_HTTPS_URL must be a valid HTTPS URL")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("PRODUCTION_HTTPS_URL must not contain userinfo")
    if not hostname:
        raise ValueError("PRODUCTION_HTTPS_URL must include a hostname")
    if ":" in parsed.netloc and not parsed.netloc.rsplit(":", maxsplit=1)[1].isdigit():
        raise ValueError("PRODUCTION_HTTPS_URL has a malformed port")
    if port not in (None, 443):
        raise ValueError("PRODUCTION_HTTPS_URL must use the standard HTTPS port")
    if parsed.path not in ("", "/"):
        raise ValueError("PRODUCTION_HTTPS_URL must be an origin without a path")

    actual_host = _normalize_hostname(hostname)
    approved_host = _normalize_hostname(approved_hostname)
    if actual_host != approved_host:
        raise ValueError("PRODUCTION_HTTPS_URL hostname does not match PRODUCTION_HTTPS_HOST")
    return f"https://{actual_host}"


def main() -> int:
    try:
        validate_production_https_url(
            os.environ.get("PRODUCTION_HTTPS_URL"), os.environ.get("PRODUCTION_HTTPS_HOST")
        )
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print("Production HTTPS URL matches the approved hostname and passed syntax checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
