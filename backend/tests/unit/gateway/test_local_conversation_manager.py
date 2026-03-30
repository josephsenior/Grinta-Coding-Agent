from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from backend.gateway.conversation_manager.local_conversation_manager import (
    LocalConversationManager,
)


def test_session_needs_restart_for_unhealthy_cached_session():
    agent_session = SimpleNamespace(
        _startup_failed=False,
        _starting=False,
        controller=object(),
        is_closed=lambda: False,
    )
    healthy = SimpleNamespace(
        _closed=False,
        is_alive=True,
        agent_session=agent_session,
    )
    assert LocalConversationManager._session_needs_restart(healthy) is False

    unhealthy_cases = [
        SimpleNamespace(_closed=True, is_alive=True, agent_session=agent_session),
        SimpleNamespace(_closed=False, is_alive=False, agent_session=agent_session),
        SimpleNamespace(
            _closed=False,
            is_alive=True,
            agent_session=SimpleNamespace(
                _startup_failed=True,
                _starting=False,
                controller=object(),
                is_closed=lambda: False,
            ),
        ),
        SimpleNamespace(
            _closed=False,
            is_alive=True,
            agent_session=SimpleNamespace(
                _startup_failed=False,
                _starting=False,
                controller=object(),
                is_closed=lambda: True,
            ),
        ),
        SimpleNamespace(
            _closed=False,
            is_alive=True,
            agent_session=SimpleNamespace(
                _startup_failed=False,
                _starting=False,
                controller=None,
                is_closed=lambda: False,
            ),
        ),
        SimpleNamespace(_closed=False, is_alive=True, agent_session=None),
    ]

    for session in unhealthy_cases:
        assert LocalConversationManager._session_needs_restart(session) is True


@pytest.mark.asyncio
async def test_send_event_to_conversation_restarts_broken_cached_session(monkeypatch):
    manager = cast(Any, LocalConversationManager.__new__(LocalConversationManager))

    broken_session = SimpleNamespace(
        sid="sid-1",
        user_id="oss_user",
        _closed=False,
        is_alive=True,
        agent_session=SimpleNamespace(
            _startup_failed=False,
            _starting=False,
            controller=None,
            is_closed=lambda: False,
        ),
        dispatch=AsyncMock(),
    )
    restarted_session = SimpleNamespace(
        sid="sid-1",
        user_id="oss_user",
        _closed=False,
        is_alive=True,
        agent_session=SimpleNamespace(
            _startup_failed=False,
            _starting=False,
            controller=object(),
            is_closed=lambda: False,
        ),
        dispatch=AsyncMock(),
    )
    manager._local_agent_loops_by_sid = {"sid-1": broken_session}

    from backend.gateway.services import conversation_service

    async def fake_setup_init_conversation_settings(user_id, conversation_id):
        assert user_id == "oss_user"
        assert conversation_id == "sid-1"
        return "settings"

    maybe_start = AsyncMock(
        side_effect=lambda sid, settings, user_id: manager._local_agent_loops_by_sid.update(
            {sid: restarted_session}
        )
        or SimpleNamespace(conversation_id=sid)
    )

    monkeypatch.setattr(
        conversation_service,
        "setup_init_conversation_settings",
        fake_setup_init_conversation_settings,
    )
    manager.maybe_start_agent_loop = maybe_start

    payload = {"action": "message", "args": {"content": "hello"}}
    await manager.send_event_to_conversation("sid-1", payload)

    maybe_start.assert_awaited_once_with("sid-1", "settings", "oss_user")
    broken_session.dispatch.assert_not_awaited()
    restarted_session.dispatch.assert_awaited_once_with(payload)
