"""Production health check subcommand — HTTP liveness probe against a running server."""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx


def run_health_check(_args: Any) -> None:
    """GET ``/alive`` on the configured host/port; exit 0 only if response is healthy."""
    port = int(os.environ.get("APP_PORT") or os.environ.get("PORT") or "3000")
    host = (os.environ.get("APP_HOST") or os.environ.get("HOST") or "127.0.0.1").strip()
    probe_host = (
        "127.0.0.1" if host in ("0.0.0.0", "::", "::0") else host or "127.0.0.1"
    )
    url = f"http://{probe_host}:{port}/alive"

    try:
        response = httpx.get(url, timeout=5.0)
    except Exception as exc:
        print(f"Health check failed: could not reach {url}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if response.status_code != 200:
        print(
            f"Health check failed: HTTP {response.status_code} from {url}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    try:
        body = response.json()
    except Exception as exc:
        print("Health check failed: invalid JSON from /alive", file=sys.stderr)
        raise SystemExit(1) from exc

    if body.get("status") != "ok":
        print(f"Health check failed: unexpected payload {body!r}", file=sys.stderr)
        raise SystemExit(1)

    print(f"OK — {url} returned healthy.")
