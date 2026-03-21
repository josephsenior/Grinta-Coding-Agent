"""Live agent integration test — requires full runtime setup.

This test is excluded from default runs (marked integration).
It needs ControllerConfig, EventStream, Agent, etc. — not EventStore.
"""
import pytest

from backend.controller.agent_controller import AgentController
from backend.events.event import EventSource
from backend.events.event_store import EventStore

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.skip(reason="Test uses outdated API (EventStore, receive_action); needs full ControllerConfig/EventStream setup")
async def test_agent_complex_task():
    # Attempting to mock out the missing constructor args or pass defaults
    store = EventStore(sid="test_sid", file_store=None, user_id="test_user")
    controller = AgentController(store)
    
    # Send our message to the controller to begin
    await controller.receive_action(
        {
            "action": "message",
            "args": {
                "content": "Create a new python script called advanced_math.py that has simple functions. Do not run git commands.",
                "image_urls": [],
                "file_urls": []
            }
        },
        EventSource.USER
    )

    import json
    logs = []
    async for event in store.get_stream().subscribe():
        d = event.model_dump()
        logs.append(d)
        if d.get("data", {}).get("state") == "awaiting_user_input":
            break
            
    with open('pytest_agent_log.json', 'w') as f:
        json.dump(logs, f, indent=2)
