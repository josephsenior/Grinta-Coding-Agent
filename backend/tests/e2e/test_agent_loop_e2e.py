"""End-to-end test: verifies the agent loop fires through the real event loop.

This test catches the class of bugs where coroutines are scheduled on
throw-away event loops (the ``run_or_schedule`` root cause) and silently
orphaned.  It sends a trivial prompt and asserts that the agent enters
RUNNING state and delivers events — proving that ``step()`` actually
executed on the main event loop.

**Requirements:**
    - A running App server on ``http://127.0.0.1:{PORT}`` (default 3000).
    - A valid LLM API key configured in settings.json / env.
    - ``httpx`` and ``python-socketio`` installed.

Run with::

    pytest backend/tests/e2e/test_agent_loop_e2e.py -m integration -v

.. note::

    The test must wait for the server to fully initialize the conversation
    (signalled by an ``awaiting_user_input`` event *with a real event-stream
    id*) before sending the user message.  Without this, a race condition
    between ``_start_agent_execution`` and the user message causes the
    ``ChangeAgentStateAction(AWAITING_USER_INPUT)`` to override the RUNNING
    state set by ``_handle_user_message``, silently killing the agent loop.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import httpx
import pytest
import socketio

pytestmark = pytest.mark.skip(
    reason=(
        'Server/Web UI E2E is retired; Grinta now ships as a CLI-only coding agent. '
        'Restore this test only if the conversation server/socket UI returns.'
    )
)

BASE = os.environ.get('APP_TEST_BASE_URL', 'http://127.0.0.1:3000')

# Maximum seconds to wait for the agent to produce activity.
AGENT_TIMEOUT = int(os.environ.get('APP_TEST_AGENT_TIMEOUT', '120'))

# Maximum seconds to wait for the server to finish initializing the
# conversation (LOADING → AWAITING_USER_INPUT).
_INIT_TIMEOUT = 60

# Seconds of silence (no new events) after RUNNING before we declare done.
_IDLE_CUTOFF = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_conversation() -> str:
    """POST /api/v1/conversations and return the conversation_id."""
    r = httpx.post(f'{BASE}/api/v1/conversations', json={}, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    cid = data.get('conversation_id') or data.get('id')
    assert cid, f'No conversation_id in response: {data}'
    return cid


class _EventCollector:
    """Sync Socket.IO client that collects ``app_event`` payloads.

    Uses a background thread for the socketio receive loop so it works
    reliably under pytest (no event-loop conflicts with pytest-asyncio).

    .. important::

        Call :meth:`wait_for_ready` **before** :meth:`send_message` to
        avoid the initialisation race (see module docstring).
    """

    def __init__(self) -> None:
        self.sio = socketio.Client(logger=False)
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._terminal = threading.Event()
        # Fires when the server emits a *real* awaiting_user_input event
        # (one that carries an event-stream ``id``, not the synthetic
        # "Default state on connection" placeholder).
        self._initialized = threading.Event()
        self._saw_running = False
        self._last_event_at: float = 0.0

        @self.sio.on('*')
        def on_any(event_name: str, data: Any = None) -> None:
            if event_name != 'app_event' or not isinstance(data, dict):
                return
            with self._lock:
                self.events.append(data)
                self._last_event_at = time.monotonic()

            action = data.get('action', '')
            obs = data.get('observation', '')
            agent_state = (data.get('extras', {}).get('agent_state', '')).upper()

            # Real event-stream events carry an ``id``; the synthetic
            # "Default state on connection" fallback does not.
            has_id = data.get('id') is not None

            if agent_state == 'AWAITING_USER_INPUT' and has_id:
                self._initialized.set()

            if agent_state == 'RUNNING':
                self._saw_running = True

            if (
                action == 'finish'
                or obs in ('agent_finish',)
                or agent_state
                in (
                    'FINISHED',
                    'STOPPED',
                    'ERROR',
                    'REJECTED',
                )
            ):
                self._terminal.set()

    def connect_to(self, conversation_id: str) -> None:
        url = f'{BASE}?conversation_id={conversation_id}&latest_event_id=-1'
        self.sio.connect(url, transports=['websocket'], wait_timeout=15)

    def wait_for_ready(self, timeout: float = _INIT_TIMEOUT) -> None:
        """Block until the server finishes initialization.

        The server emits ``ChangeAgentStateAction(AWAITING_USER_INPUT)``
        at the end of ``_start_agent_execution``.  We must wait for the
        resulting ``AgentStateChangedObservation`` (which carries a real
        event-stream id) before sending a user message, otherwise the
        initialization action races with **our** message and overrides
        the RUNNING state.
        """
        if not self._initialized.wait(timeout=timeout):
            with self._lock:
                n = len(self.events)
            raise TimeoutError(
                f'Server did not reach awaiting_user_input within {timeout}s. '
                f'Events received: {n}'
            )

    def send_message(self, content: str) -> None:
        self.sio.emit(
            'app_user_action',
            {
                'action': 'message',
                'args': {'content': content, 'image_urls': []},
            },
        )

    def wait_for_activity(self, timeout: float) -> None:
        """Wait until the agent finishes OR stalls after entering RUNNING."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._terminal.is_set():
                return
            if (
                self._saw_running
                and self._last_event_at > 0
                and (time.monotonic() - self._last_event_at) > _IDLE_CUTOFF
            ):
                return
            time.sleep(1)
        with self._lock:
            n = len(self.events)
        raise TimeoutError(
            f'Timed out after {timeout}s. '
            f'Events received: {n}, '
            f'saw_running: {self._saw_running}'
        )

    def disconnect(self) -> None:
        if self.sio.connected:
            self.sio.disconnect()

    # -- Convenience queries --------------------------------------------------

    def agent_states(self) -> list[str]:
        with self._lock:
            return [
                e.get('extras', {}).get('agent_state', '').upper()
                for e in self.events
                if e.get('extras', {}).get('agent_state')
            ]

    def all_text(self) -> str:
        """Concatenate all message + content fields across events."""
        with self._lock:
            parts: list[str] = []
            for e in self.events:
                parts.append(e.get('message', ''))
                parts.append(e.get('content', ''))
                parts.append(str(e.get('args', {}).get('content', '')))
            return ' '.join(parts)

    def has_error(self) -> str | None:
        with self._lock:
            for e in self.events:
                if (e.get('extras', {}).get('agent_state', '')).upper() == 'ERROR':
                    return e.get('message', 'unknown error')
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_agent_responds_to_prompt() -> None:
    """Send a trivial prompt and assert the agent enters RUNNING.

    The critical assertion is that events arrive and the agent enters RUNNING
    (proving step() fired on the main loop).  The exact content of the
    agent's response is not checked — LLM output is non-deterministic.
    """
    cid = _create_conversation()
    collector = _EventCollector()
    try:
        collector.connect_to(cid)
        collector.wait_for_ready()
        collector.send_message('Say exactly: Hello World')
        collector.wait_for_activity(timeout=AGENT_TIMEOUT)
    finally:
        collector.disconnect()

    err = collector.has_error()
    assert err is None, f'Agent entered ERROR state: {err}'

    with collector._lock:
        n_events = len(collector.events)
    assert n_events > 0, 'No events received from the agent'

    # step() must have fired — RUNNING state must appear.
    states = collector.agent_states()
    assert 'RUNNING' in states, (
        f'RUNNING state never seen — step() may not have fired. States: {states}'
    )


@pytest.mark.integration
def test_event_stream_delivers_state_transitions() -> None:
    """Verify events are delivered and the agent transitions through states.

    A healthy agent should at minimum transition to RUNNING, proving that
    ``step()`` executed and events were dispatched through the main event
    loop (not orphaned on a disposable loop).
    """
    cid = _create_conversation()
    collector = _EventCollector()
    try:
        collector.connect_to(cid)
        collector.wait_for_ready()
        collector.send_message('What is 2 + 2?')
        collector.wait_for_activity(timeout=AGENT_TIMEOUT)
    finally:
        collector.disconnect()

    states = collector.agent_states()
    assert len(states) >= 2, (
        f'Expected at least 2 state transitions, got {len(states)}: {states}'
    )
    assert 'RUNNING' in states, (
        f'RUNNING state never seen — step() may not have fired. States: {states}'
    )
