from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock
from types import SimpleNamespace

from backend.api.session.session import Session
from backend.events import EventStreamSubscriber


class TestSessionPublishQueue(unittest.IsolatedAsyncioTestCase):
    def _make_session(self, maxsize: int = 2) -> Session:
        session = Session.__new__(Session)
        session._publish_queue = asyncio.Queue(maxsize=maxsize)
        session.logger = MagicMock()
        return session

    @staticmethod
    def _user_message(content: str) -> dict[str, object]:
        return {
            "id": 10,
            "action": "message",
            "source": "user",
            "message": content,
            "args": {"content": content},
        }

    @staticmethod
    def _streaming_chunk(text: str) -> dict[str, object]:
        return {
            "id": 11,
            "action": "streaming_chunk",
            "source": "agent",
            "args": {"chunk": text},
        }

    @staticmethod
    def _state_change(state: str) -> dict[str, object]:
        return {
            "id": 12,
            "observation": "agent_state_changed",
            "source": "agent",
            "extras": {"agent_state": state},
        }

    async def test_send_preserves_user_message_by_evicting_streaming_chunk(self):
        session = self._make_session()
        await session._publish_queue.put(self._streaming_chunk("hello"))
        await session._publish_queue.put(self._state_change("running"))

        await session.send(self._user_message("hi"))

        queued = [
            session._publish_queue.get_nowait(),
            session._publish_queue.get_nowait(),
        ]
        assert [item.get("action") or item.get("observation") for item in queued] == [
            "agent_state_changed",
            "message",
        ]

    async def test_send_drops_incoming_streaming_chunk_when_queue_has_only_important_events(self):
        session = self._make_session()
        first = self._user_message("first")
        second = self._state_change("running")
        await session._publish_queue.put(first)
        await session._publish_queue.put(second)

        await session.send(self._streaming_chunk("late chunk"))

        queued = [
            session._publish_queue.get_nowait(),
            session._publish_queue.get_nowait(),
        ]
        assert queued == [first, second]


class TestSessionDispatchSubscriptionHealing(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_restores_missing_core_subscriptions(self):
        session = Session.__new__(Session)
        session.sid = "sid-1"
        session.logger = MagicMock()
        session._init_ready = asyncio.Event()
        session._init_ready.set()

        subscribe_calls: list[tuple[object, str]] = []
        event_stream = SimpleNamespace(_subscribers={})
        event_stream.add_event = MagicMock()

        def subscribe(subscriber_id, callback, callback_id):
            subscribe_calls.append((subscriber_id, callback_id))
            event_stream._subscribers.setdefault(subscriber_id, {})[callback_id] = callback

        event_stream.subscribe = subscribe

        controller = SimpleNamespace(id="controller-1", on_event=MagicMock())
        memory = SimpleNamespace(on_event=MagicMock())
        session.agent_session = SimpleNamespace(
            _init_ready=session._init_ready,
            event_stream=event_stream,
            controller=controller,
            memory=memory,
        )

        await session.dispatch({"action": "message", "args": {"content": "hi"}})

        assert subscribe_calls == [
            (EventStreamSubscriber.SERVER, "sid-1"),
            (EventStreamSubscriber.AGENT_CONTROLLER, "controller-1"),
            (EventStreamSubscriber.MEMORY, "sid-1"),
        ]
        event_stream.add_event.assert_called_once()
