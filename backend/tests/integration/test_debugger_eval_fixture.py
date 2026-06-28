"""Integration test mirroring Cursor tool-eval debugger start on ``test_tools.py``.

Validates that:
  * the eval-style fixture completes or fails within the startup budget cap;
  * high ``action.timeout`` values do not extend the DAP start wall clock past
    ``DEBUGGER_START_TIMEOUT_SECONDS``;
  * responses are actionable (started or phase-specific error), not a bare hang.
"""

from __future__ import annotations

import sys
import textwrap
import time

import pytest

debugpy = pytest.importorskip('debugpy', reason='debugpy not installed')

from backend.core.constants import DEBUGGER_START_TIMEOUT_SECONDS
from backend.execution.server.debugger import DAPDebugManager
from backend.ledger.action.debugger import DebuggerAction
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation.debugger import DebuggerObservation


def _write_eval_fixture(workspace: object) -> object:
    program = workspace / 'test_tools.py'
    program.write_text(
        textwrap.dedent(
            """
            print("ok")
            """
        ).strip(),
        encoding='utf-8',
    )
    return program


@pytest.mark.integration
@pytest.mark.parametrize('action_timeout', [None, 120.0])
def test_eval_fixture_start_respects_startup_budget_cap(
    tmp_path, action_timeout: float | None
) -> None:
    """Mimic eval: ``adapter=python``, ``program=test_tools.py``."""
    _write_eval_fixture(tmp_path)
    manager = DAPDebugManager(str(tmp_path))

    kwargs: dict[str, object] = {
        'debug_action': 'start',
        'adapter': 'python',
        'program': 'test_tools.py',
        'python': sys.executable,
    }
    if action_timeout is not None:
        kwargs['timeout'] = action_timeout

    start = time.monotonic()
    obs = manager.handle(DebuggerAction(**kwargs))
    elapsed = time.monotonic() - start
    manager.close_all()

    # Startup must not burn the full eval/pending 120 s floor.
    assert elapsed < float(DEBUGGER_START_TIMEOUT_SECONDS) + 15.0, (
        f'elapsed={elapsed:.1f}s (cap={DEBUGGER_START_TIMEOUT_SECONDS})'
    )

    if isinstance(obs, DebuggerObservation):
        assert '"state": "started"' in obs.content
    else:
        assert isinstance(obs, ErrorObservation)
        content = obs.content
        assert (
            'startup_phase:' in content
            or 'debugpy' in content.lower()
            or 'DAP' in content
            or 'debugger program' in content
        ), content
