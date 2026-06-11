"""Server-startup detection helpers extracted from :class:`BashSession`.

Long-running commands such as dev servers may print a "ready" line to
stdout. These helpers detect that line and stash a ``DetectedServer``
record on the session for the runtime to emit as an observation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.execution.utils.bash import BashSession
    from backend.execution.utils.server_detector import DetectedServer


def _detect_server_startup(orch: BashSession, output: str) -> None:
    """Check for server startup in command output."""
    from backend.execution.utils.server_detector import detect_server_from_output

    detected_server = detect_server_from_output(output, perform_health_check=True)
    if detected_server and not hasattr(orch, '_last_detected_server_url'):
        from backend.core.logger import app_logger as logger

        logger.info(
            '🚀 Server detected: %s (health: %s)',
            detected_server.url,
            detected_server.health_status,
        )
        # Store for runtime to emit ServerReadyObservation - only detect each server once
        setattr(orch, '_last_detected_server', detected_server)
        setattr(orch, '_last_detected_server_url', detected_server.url)


def get_detected_server(orch: BashSession) -> 'DetectedServer | None':
    """Get and clear the last detected server."""
    if hasattr(orch, '_last_detected_server'):
        server = orch._last_detected_server
        del orch._last_detected_server
        del orch._last_detected_server_url
        return server
    return None
