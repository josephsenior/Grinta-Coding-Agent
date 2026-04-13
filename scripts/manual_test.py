import os
import sys
import threading
import time
from typing import Any

import httpx
import socketio

BASE = os.getenv('APP_BASE_URL', 'http://127.0.0.1:3000')
AGENT_TIMEOUT = 600
_INIT_TIMEOUT = 120
_IDLE_CUTOFF = 120
_CONNECT_RETRIES = 5
_CREATE_CONV_RETRIES = 8

def _create_conversation() -> str:
    print('Creating conversation...')
    last_error: Exception | None = None
    for attempt in range(1, _CREATE_CONV_RETRIES + 1):
        try:
            r = httpx.post(f'{BASE}/api/v1/conversations', json={}, timeout=120.0)
            r.raise_for_status()
            data = r.json()
            cid = data.get('conversation_id') or data.get('id')
            if not cid:
                raise RuntimeError(f'Conversation id missing in response: {data}')
            print(f'Conversation ID: {cid}')
            return cid
        except Exception as exc:
            last_error = exc
            print(f'Create conversation attempt {attempt}/{_CREATE_CONV_RETRIES} failed: {exc}')
            if attempt < _CREATE_CONV_RETRIES:
                time.sleep(2)
    raise RuntimeError(
        f'Could not create conversation after {_CREATE_CONV_RETRIES} attempts: {last_error}'
    )

class EventCollector:
    def __init__(self) -> None:
        self.sio = socketio.Client(logger=False)
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._terminal = threading.Event()
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
            has_id = data.get('id') is not None

            msg = data.get('message')
            if msg:
                snippet = str(msg).replace('\n', ' ')[:220]
                print(f'[AGENT MESSAGE]: {snippet}')

            content = data.get('content')
            if content:
                snippet = str(content).replace('\n', ' ')[:220]
                print(f'[AGENT CONTENT]: {snippet}')

            tool_call = data.get('args')
            if action:
                if action != 'system':
                    if isinstance(tool_call, dict):
                        keys = ','.join(sorted(tool_call.keys()))
                        print(f'[AGENT ACTION]: {action} args_keys=[{keys}]')
                    else:
                        print(f'[AGENT ACTION]: {action}')
            if obs:
                print(f'[AGENT OBSERVATION]: {str(obs)[:200]}...')
            if agent_state:
                pass # print(f"[AGENT STATE]: {agent_state}")

            if agent_state == 'AWAITING_USER_INPUT' and has_id:
                self._initialized.set()

            if agent_state == 'RUNNING':
                self._saw_running = True

            if action == 'finish' or obs == 'agent_finish' or agent_state in ('FINISHED', 'STOPPED', 'ERROR', 'REJECTED'):
                self._terminal.set()

    def connect_to(self, conversation_id: str) -> None:
        url = f'{BASE}?conversation_id={conversation_id}&latest_event_id=-1'
        last_error: Exception | None = None
        for attempt in range(1, _CONNECT_RETRIES + 1):
            try:
                # Let engine.io negotiate transports (polling -> websocket upgrade)
                # because websocket-only can fail during transient startup pressure.
                self.sio.connect(url, wait_timeout=20)
                return
            except Exception as exc:
                last_error = exc
                if attempt < _CONNECT_RETRIES:
                    time.sleep(1.5)
        raise RuntimeError(
            f'Could not connect Socket.IO after {_CONNECT_RETRIES} attempts: {last_error}'
        )

    def wait_for_ready(self, timeout: float = _INIT_TIMEOUT) -> None:
        if not self._initialized.wait(timeout=timeout):
            raise TimeoutError('Server did not reach awaiting_user_input')

    def send_message(self, content: str) -> None:
        print(f'Sending message: {content}')
        self.sio.emit(
            'app_user_action',
            {
                'action': 'message',
                'args': {'content': content, 'image_urls': []},
            },
        )

    def wait_for_activity(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._terminal.is_set():
                print('Terminal state reached. Finishing wait.')
                return
            if (self._saw_running and self._last_event_at > 0 and (time.monotonic() - self._last_event_at) > _IDLE_CUTOFF):
                print(f'Idle cutoff reached ({_IDLE_CUTOFF}s). Finishing wait.')
                return
            time.sleep(1)
        print('Timeout reached waiting for activity.')

    def disconnect(self) -> None:
        if self.sio.connected:
            self.sio.disconnect()

def test_prompt(prompt: str):
    cid = _create_conversation()
    collector = EventCollector()
    try:
        collector.connect_to(cid)
        print('Waiting for ready sequence...')
        collector.wait_for_ready()
        collector.send_message(prompt)
        print('Waiting for agent to finish...')
        collector.wait_for_activity(timeout=AGENT_TIMEOUT)
    finally:
        collector.disconnect()

if __name__ == '__main__':
    prompt = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'I want you to write a complex python script that calculates fibonacci series and saves the execution logs into a markdown file, running it, and updating another file called summary.md with execution results'
    test_prompt(prompt)
