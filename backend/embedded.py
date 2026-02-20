"""Embedded (single-process) mode for solo local-first use.

Starts the Forge FastAPI/Socket.IO backend in a *background thread* using
uvicorn, waits until it is ready, then launches the Textual TUI in the main
thread.  This means users only need **one terminal** instead of two.

Usage::

    python -m backend.embedded             # starts on default port 3000
    python -m backend.embedded --port 3001 # custom port
    python -m backend.embedded --verbose   # debug logging
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time

logger = logging.getLogger("forge.embedded")

_STARTUP_POLL_INTERVAL = 0.25   # seconds between readiness probes
_STARTUP_TIMEOUT = 30.0         # seconds before giving up


# ---------------------------------------------------------------------------
# Server thread
# ---------------------------------------------------------------------------

def _run_server(host: str, port: int) -> None:
    """Target for the background server thread."""
    import uvicorn  # imported here so the main thread can start fast

    uvicorn.run(
        "backend.api.listen:app",
        host=host,
        port=port,
        log_level="error",   # suppress uvicorn's startup noise in embedded mode
        reload=False,        # reload incompatible with threads
    )


def _wait_for_server(host: str, port: int, timeout: float = _STARTUP_TIMEOUT) -> bool:
    """Poll the health endpoint until the server is ready or the timeout expires.

    Returns True when the server responds, False on timeout.
    """
    import httpx

    url = f"http://{host}:{port}/api/v1/alive"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(url, timeout=2.0)
            if resp.is_success:
                return True
        except Exception:
            pass
        time.sleep(_STARTUP_POLL_INTERVAL)
    return False


# ---------------------------------------------------------------------------
# Embedded entry point
# ---------------------------------------------------------------------------

def run_embedded(host: str = "127.0.0.1", port: int = 3000, verbose: bool = False) -> None:
    """Start server in background thread, then run TUI in the foreground.

    This is the single-process path for local solo users — no second terminal
    or separate server process required.
    """
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        force=True,
    )

    print(f"🔧 Forge embedded mode — starting server on http://{host}:{port} …")

    # Start the server in a daemon thread so it dies automatically when the
    # TUI (main thread) exits.
    server_thread = threading.Thread(
        target=_run_server,
        args=(host, port),
        daemon=True,
        name="forge-server",
    )
    server_thread.start()

    # Wait for the server to become healthy
    print("   Waiting for server readiness…", end="", flush=True)
    ready = _wait_for_server(host, port)
    if not ready:
        print(" FAILED")
        print(
            f"❌  Server did not become ready within {_STARTUP_TIMEOUT}s. "
            "Check logs above for errors.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(" ready ✓")

    # Launch the TUI
    from tui.app import ForgeApp
    from tui.client import ForgeClient

    base_url = f"http://{host}:{port}"
    client = ForgeClient(base_url=base_url)
    app = ForgeApp(client)

    try:
        app.run()
    finally:
        # Server thread is a daemon — it will exit on its own.
        # Give uvicorn a moment to finish any in-flight requests.
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="forge",
        description=(
            "Forge — single-process embedded mode.  "
            "Starts the backend server and TUI together in one terminal."
        ),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("HOST", "127.0.0.1"),
        help="Host to bind the embedded server to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "3000")),
        help="Port for the embedded server (default: 3000)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    run_embedded(host=args.host, port=args.port, verbose=args.verbose)


if __name__ == "__main__":
    main()
