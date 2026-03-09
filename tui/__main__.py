"""Entry point: ``python -m tui [--port PORT] [--host HOST] [--dev] [--embedded]``."""

from __future__ import annotations

import argparse
import logging
import os
import sys


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="forge-tui",
        description="Forge TUI — Textual-based terminal interface for the Forge coding agent",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Forge backend hostname (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=3000,
        help="Forge backend port (default: 3000)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable dev mode: auto-reload on source changes under tui/",
    )
    parser.add_argument(
        "--embedded",
        action="store_true",
        help=(
            "Single-process embedded mode: start the backend server automatically "
            "in the same process, then launch the TUI.  No second terminal needed."
        ),
    )
    return parser.parse_args()


def _run_app(host: str, port: int, verbose: bool) -> None:
    """Create the client and run the Textual app (single invocation)."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        force=True,
    )

    from tui.app import ForgeApp
    from tui.client import ForgeClient

    base_url = f"http://{host}:{port}"
    client = ForgeClient(base_url=base_url)
    app = ForgeApp(client)
    app.run()


def _run_dev_mode(host: str, port: int, verbose: bool) -> None:
    """Run the TUI under a watchfiles reload loop.

    When any ``*.py`` file under ``tui/`` changes the process is
    restarted automatically so the developer sees the update immediately.
    """
    try:
        from watchfiles import run_process, PythonFilter  # type: ignore[import-untyped]
    except ImportError:
        print(
            "watchfiles is required for --dev mode.  Install it with:\n"
            "  pip install watchfiles",
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine the directory to watch
    tui_dir = os.path.dirname(os.path.abspath(__file__))

    print(f"[dev] Watching {tui_dir} for changes — Ctrl+C to quit")

    # Build the target command.  run_process will restart a *function* in a
    # subprocess each time a change is detected.
    def _target(*_args: object) -> None:  # signature expected by run_process
        _run_app(host, port, verbose)

    run_process(
        tui_dir,
        target=_target,
        watch_filter=PythonFilter(),
        # Grace period before re-launching so editors don't trigger double saves
        debounce=800,
    )


def main() -> None:
    """Parse CLI args and either run directly or in dev-reload mode."""
    args = _parse_args()

    if args.embedded:
        from backend.embedded import run_embedded

        run_embedded(host=args.host, port=args.port, verbose=args.verbose)
    elif args.dev:
        _run_dev_mode(args.host, args.port, args.verbose)
    else:
        _run_app(args.host, args.port, args.verbose)


if __name__ == "__main__":
    main()
