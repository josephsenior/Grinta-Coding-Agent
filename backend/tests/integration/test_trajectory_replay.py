import json
import tempfile

from backend.events import EventSource
from backend.events.observation import NullObservation
from backend.events.stream import EventStream
from backend.api.routes.trajectory import get_trajectory
from backend.api.session.conversation import ServerConversation
from backend.core.config import ForgeConfig
from backend.storage.local_file_store import LocalFileStore


async def test_trajectory_replay_since_id_and_ordering() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        file_store = LocalFileStore(tmpdir)
        event_stream = EventStream("test-conversation", file_store)
        config = ForgeConfig()
        try:
            for content in ["e0", "e1", "e2", "e3", "e4"]:
                event_stream.add_event(
                    NullObservation(content=content), EventSource.AGENT
                )

            conversation = ServerConversation(
                sid="test-conversation",
                file_store=file_store,
                config=config,
                user_id="test-user",
                event_stream=event_stream,
            )

            resp = await get_trajectory(
                conversation_id="test-conversation",
                since_id=1,
                limit=None,
                conversation=conversation,
            )
            payload = json.loads(resp.body)
            ids = [evt["id"] for evt in payload["trajectory"]]
            assert ids == [2, 3, 4]

            resp_limited = await get_trajectory(
                conversation_id="test-conversation",
                since_id=1,
                limit=2,
                conversation=conversation,
            )
            payload_limited = json.loads(resp_limited.body)
            ids_limited = [evt["id"] for evt in payload_limited["trajectory"]]
            assert ids_limited == [2, 3]
        finally:
            event_stream.close()

