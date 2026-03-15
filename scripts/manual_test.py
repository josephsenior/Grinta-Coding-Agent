import os
import threading
import time
from typing import Any
import sys

import httpx
import socketio

BASE = "http://127.0.0.1:3000"
AGENT_TIMEOUT = 300
_INIT_TIMEOUT = 60
_IDLE_CUTOFF = 60

def _create_conversation() -> str:
    print("Creating conversation...")
    r = httpx.post(f"{BASE}/api/v1/conversations", json={}, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    cid = data.get("conversation_id") or data.get("id")
    print(f"Conversation ID: {cid}")
    return cid

class EventCollector:
    def __init__(self) -> None:
        self.sio = socketio.Client(logger=False)
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._terminal = threading.Event()
        self._initialized = threading.Event()
        self._saw_running = False
        self._last_event_at: float = 0.0

        @self.sio.on("*")
        def on_any(event_name: str, data: Any = None) -> None:
            if event_name != "forge_event" or not isinstance(data, dict):
                return
            with self._lock:
                self.events.append(data)
                self._last_event_at = time.monotonic()

            action = data.get("action", "")
            obs = data.get("observation", "")
            agent_state = (data.get("extras", {}).get("agent_state", "")).upper()
            has_id = data.get("id") is not None

            msg = data.get("message")
            if msg:
                print(f"[AGENT MESSAGE]: {msg}")
            
            content = data.get("content")
            if content:
                print(f"[AGENT CONTENT]: {content}")
                
            tool_call = data.get("args")
            if action:
                print(f"[AGENT ACTION]: {action} args={tool_call}")
            if obs:
                print(f"[AGENT OBSERVATION]: {str(obs)[:200]}...")
            if agent_state:
                pass # print(f"[AGENT STATE]: {agent_state}")

            if agent_state == "AWAITING_USER_INPUT" and has_id:
                self._initialized.set()

            if agent_state == "RUNNING":
                self._saw_running = True

            if action == "finish" or obs == "agent_finish" or agent_state in ("FINISHED", "STOPPED", "ERROR", "REJECTED"):
                self._terminal.set()

    def connect_to(self, conversation_id: str) -> None:
        url = f"{BASE}?conversation_id={conversation_id}&latest_event_id=-1"
        self.sio.connect(url, transports=["websocket"], wait_timeout=15)

    def wait_for_ready(self, timeout: float = _INIT_TIMEOUT) -> None:
        if not self._initialized.wait(timeout=timeout):
            raise TimeoutError("Server did not reach awaiting_user_input")

    def send_message(self, content: str) -> None:
        print(f"Sending message: {content}")
        self.sio.emit(
            "forge_user_action",
            {
                "action": "message",
                "args": {"content": content, "image_urls": []},
            },
        )

    def wait_for_activity(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._terminal.is_set():
                print("Terminal state reached. Finishing wait.")
                return
            if (self._saw_running and self._last_event_at > 0 and (time.monotonic() - self._last_event_at) > _IDLE_CUTOFF):
                print(f"Idle cutoff reached ({_IDLE_CUTOFF}s). Finishing wait.")
                return
            time.sleep(1)
        print("Timeout reached waiting for activity.")

    def disconnect(self) -> None:
        if self.sio.connected:
            self.sio.disconnect()

def test_prompt(prompt: str):
    cid = _create_conversation()
    collector = EventCollector()
    try:
        collector.connect_to(cid)
        print("Waiting for ready sequence...")
        collector.wait_for_ready()
        collector.send_message(prompt)
        print("Waiting for agent to finish...")
        collector.wait_for_activity(timeout=AGENT_TIMEOUT)
    finally:
        collector.disconnect()

if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "I want you to write a complex python script that calculates fibonacci series and saves the execution logs into a markdown file, running it, and updating another file called summary.md with execution results"
    test_prompt(prompt)
