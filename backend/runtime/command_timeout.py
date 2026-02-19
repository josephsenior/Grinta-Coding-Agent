"""Command timeout heuristics for Runtime action execution.

Extracts server/long-running command detection and timeout assignment
from the monolithic Runtime base class.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.events.action import Action

# Patterns for commands that should run without timeout (servers, watchers, etc.)
_LONG_RUNNING_PATTERNS: tuple[str, ...] = (
    "python -m http.server",
    "python3 -m http.server",
    "npm run dev",
    "npm start",
    "yarn dev",
    "yarn start",
    "pnpm dev",
    "pnpm start",
    "node server",
    "nodemon",
    "flask run",
    "django-admin runserver",
    "python manage.py runserver",
    "uvicorn",
    "gunicorn",
    "hypercorn",
    "daphne",
    "streamlit run",
    "gradio",
    "rails server",
    "bundle exec rails",
    "php artisan serve",
    "go run",
    "./server",
    "java -jar",
)


class CommandTimeoutMixin:
    """Mixin providing command timeout heuristics for Runtime subclasses."""

    sid: str
    config: Any
    process_manager: Any

    def _is_long_running_command(self, command: str) -> bool:
        """Detect if a command is a long-running server/process.

        Args:
            command: The bash command to check

        Returns:
            True if command should run without timeout, False otherwise
        """
        cmd_lower = command.lower().strip()
        return any(pattern in cmd_lower for pattern in _LONG_RUNNING_PATTERNS)

    def _set_action_timeout(self, event: Action) -> None:
        """Set appropriate timeout for action based on type.

        Args:
            event: Action to set timeout for
        """
        from backend.events.action import CmdRunAction

        if event.timeout is not None:
            return

        # Check if this is a long-running command (server, etc.)
        if isinstance(event, CmdRunAction) and self._is_long_running_command(
            event.command
        ):
            logger.info(
                "Detected long-running command, removing timeout: %s",
                event.command[:100],
            )
            event.set_hard_timeout(None, blocking=False)

            # Register long-running process for cleanup
            if hasattr(self, "process_manager"):
                command_id = f"{self.sid}_{event.id}_{int(time.time())}"
                self.process_manager.register_process(event.command, command_id)
        else:
            # Normal commands get standard timeout
            event.set_hard_timeout(self.config.runtime_config.timeout, blocking=False)
