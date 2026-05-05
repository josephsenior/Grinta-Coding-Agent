"""Integration test: real ``debugpy.adapter`` cold start + stop.

Skipped when ``debugpy`` is unavailable. Asserts that:
  * the cold ``start()`` cycle completes within a generous budget (no hang);
  * the session can be ``stop()``ped cleanly without leaking the adapter pid;
  * granular DAP progress lines are emitted via the app logger.

This guards against the regression that produced multi-minute debugger latency
in `logs/workspaces/.../app.log` (PENDING_ACTION_TIMEOUT_CLEARED at 600 s).
"""

from __future__ import annotations

import logging
import sys
import textwrap
import time

import pytest

debugpy = pytest.importorskip('debugpy', reason='debugpy not installed')

from backend.execution.debugger import DAPDebugManager  # noqa: E402
from backend.ledger.action.debugger import DebuggerAction  # noqa: E402
from backend.ledger.observation import ErrorObservation  # noqa: E402
from backend.ledger.observation.debugger import DebuggerObservation  # noqa: E402

# Cold start budget on developer machines. Full-suite runs on Windows can
# intermittently starve subprocess spawn; 60s keeps the guardrail without flakes.
COLD_START_BUDGET_SEC = 60.0


@pytest.mark.integration
def test_real_debugpy_cold_start_and_stop(tmp_path) -> None:
    program = tmp_path / 'noop.py'
    program.write_text(
        textwrap.dedent(
            """
            import time
            time.sleep(0.05)
            """
        ).strip()
    )

    captured: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    from backend.core.logger import app_logger

    handler = _CaptureHandler(level=logging.INFO)
    start: DebuggerObservation | ErrorObservation
    for attempt in range(2):
        manager = DAPDebugManager(str(tmp_path))
        captured.clear()
        app_logger.addHandler(handler)
        prior_level = app_logger.level
        app_logger.setLevel(logging.INFO)
        try:
            start = manager.handle(
                DebuggerAction(
                    debug_action='start',
                    adapter='python',
                    program=str(program),
                    python=sys.executable,
                    timeout=COLD_START_BUDGET_SEC,
                )
            )
        finally:
            app_logger.removeHandler(handler)
            app_logger.setLevel(prior_level)
        if isinstance(start, DebuggerObservation) and '"state": "started"' in (
            start.content
        ):
            break
        manager.close_all()
        if attempt == 1:
            assert isinstance(start, DebuggerObservation), getattr(
                start, 'content', start
            )
        time.sleep(2.0)
    assert isinstance(start, DebuggerObservation), getattr(start, 'content', start)
    payload = start.content
    assert '"state": "started"' in payload, payload

    session_id = next(iter(manager.sessions))
    stop = manager.handle(
        DebuggerAction(debug_action='stop', session_id=session_id, timeout=10.0)
    )
    assert isinstance(stop, DebuggerObservation), getattr(stop, 'content', stop)
    assert session_id not in manager.sessions

    progress_messages = captured
    # DAP logs are ``[{msg_type}] {message}`` from ``_dap_log``, not ``DAP: ...``.
    assert any('spawning adapter' in m for m in progress_messages), progress_messages
    assert any('DAP session started successfully' in m for m in progress_messages), (
        progress_messages
    )
