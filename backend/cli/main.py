"""Grinta CLI — zero-config terminal entry point.

Usage::

    grinta              # Launch interactive REPL
    grinta --help       # Show help
    python -m backend.cli.main   # Alternative invocation
"""

from __future__ import annotations

import asyncio
import io
import logging
import sys


def _setup_logging() -> None:
    """Redirect all backend logging through RichHandler so stray prints
    don't break the TUI layout."""
    from rich.logging import RichHandler

    handler = RichHandler(
        show_time=False,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        level=logging.WARNING,
    )
    # Replace root handlers.
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.WARNING)

    # Also silence noisy libraries.
    for name in ("uvicorn", "httpcore", "httpx", "asyncio", "filelock"):
        logging.getLogger(name).setLevel(logging.ERROR)


def _suppress_stdout() -> io.TextIOWrapper | None:
    """Capture stray stdout writes from the backend into a buffer."""
    original = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)
    return original


def _restore_stdout(original: io.TextIOWrapper | None) -> None:
    if original is not None:
        sys.stdout = original


async def _async_main(
    *,
    model: str | None = None,
    project: str | None = None,
) -> None:
    from rich.console import Console

    from backend.core.config import load_app_config
    from backend.cli.config_manager import needs_onboarding, run_onboarding
    from backend.cli.repl import Repl

    console = Console()

    # -- load config -------------------------------------------------------
    config = load_app_config()

    # -- apply CLI overrides (non-persistent) ------------------------------
    if model:
        llm_cfg = config.get_llm_config()
        llm_cfg.model = model
    if project:
        from pathlib import Path

        config.project_root = str(Path(project).resolve())

    # -- onboarding if needed ----------------------------------------------
    if needs_onboarding(config):
        config = run_onboarding()
        if model:
            llm_cfg = config.get_llm_config()
            llm_cfg.model = model
        if project:
            from pathlib import Path

            config.project_root = str(Path(project).resolve())
        # Re-check after onboarding.
        if needs_onboarding(config):
            console.print("[red]No API key configured. Exiting.[/red]")
            return

    # -- redirect backend noise --------------------------------------------
    _setup_logging()

    # -- launch REPL -------------------------------------------------------
    repl = Repl(config, console)
    await repl.run()


def main(
    *,
    model: str | None = None,
    project: str | None = None,
) -> None:
    """Synchronous entry point for the ``grinta`` console_script."""
    try:
        asyncio.run(_async_main(model=model, project=project))
    except KeyboardInterrupt:
        # Top-level Ctrl+C — exit cleanly without traceback.
        print()  # newline after ^C


if __name__ == "__main__":
    main()
