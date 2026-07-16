"""Integration test: real ``debugpy.adapter`` cold start + stop.

Skipped when ``debugpy`` is unavailable. Asserts that:
  * the cold ``start()`` cycle completes within a generous budget (no hang);
  * the session can be ``stop()``ped cleanly without leaking the adapter pid.

This guards against the regression that produced multi-minute debugger latency
in `logs/workspaces/.../app.log` (PENDING_ACTION_TIMEOUT_CLEARED at 600 s).
"""

from __future__ import annotations

import os
import sys
import textwrap
import time

import pytest

debugpy = pytest.importorskip('debugpy', reason='debugpy not installed')

from backend.core.constants import DEBUGGER_START_TIMEOUT_SECONDS
from backend.execution.dap import DAPDebugManager  # noqa: E402
from backend.ledger.action.debugger import DebuggerAction  # noqa: E402
from backend.ledger.observation import ErrorObservation  # noqa: E402
from backend.ledger.observation.debugger import DebuggerObservation  # noqa: E402


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv('GITHUB_ACTIONS') == 'true',
    reason='debugpy cold start is flaky/restricted in GitHub Actions CI environment',
)
def test_real_debugpy_cold_start_and_stop(tmp_path, monkeypatch) -> None:
    from backend.core import constants

    monkeypatch.setattr(constants, 'DEBUGGER_START_TIMEOUT_SECONDS', 120.0)
    from backend.execution.dap import _dap_spawn_utils

    monkeypatch.setattr(_dap_spawn_utils, 'DEBUGGER_START_TIMEOUT_SECONDS', 120.0)

    program = tmp_path / 'noop.py'
    program.write_text(
        textwrap.dedent(
            """
            import time
            time.sleep(0.05)
            """
        ).strip()
    )

    start: DebuggerObservation | ErrorObservation
    manager = DAPDebugManager(str(tmp_path))
    for attempt in range(2):
        manager = DAPDebugManager(str(tmp_path))
        t0 = time.monotonic()
        start = manager.handle(
            DebuggerAction(
                debug_action='start',
                adapter='python',
                program=str(program),
                python=sys.executable,
                timeout=120.0,
            )
        )
        elapsed = time.monotonic() - t0
        assert elapsed < float(DEBUGGER_START_TIMEOUT_SECONDS) + 15.0, (
            f'cold start took {elapsed:.1f}s'
        )
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
