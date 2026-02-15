"""Entry point: ``python -m backend.tui [--port PORT] [--host HOST]``."""

from __future__ import annotations

import argparse
import logging


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
    return parser.parse_args()


def main() -> None:
    """Parse CLI args, create the client, and run the Textual app."""
    args = _parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from backend.tui.app import ForgeApp
    from backend.tui.client import ForgeClient

    base_url = f"http://{args.host}:{args.port}"
    client = ForgeClient(base_url=base_url)
    app = ForgeApp(client)
    app.run()


if __name__ == "__main__":
    main()
