"""Full end-to-end trace: create conversation -> connect socket -> send message -> wait for agent response."""

import asyncio
import json

import httpx
import pytest
import socketio

BASE = 'http://127.0.0.1:3000'


async def _run_e2e_trace():
    # 1. Create a new conversation
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        r = await client.post(
            '/api/v1/conversations',
            json={
                'initial_user_msg': 'say hello',
            },
        )
        print(f'[HTTP] POST /conversations -> {r.status_code}: {r.text[:300]}')
        if r.status_code not in (200, 201):
            print('FAILED to create conversation, trying without body...')
            r = await client.post('/api/v1/conversations', json={})
            print(f'[HTTP] POST /conversations -> {r.status_code}: {r.text[:300]}')

        conv_id = None
        try:
            data = r.json()
            conv_id = data.get('conversation_id') or data.get('id')
        except Exception:
            pass

        if not conv_id:
            print('Could not get conversation_id, aborting')
            return

        print(f'\n[INFO] conversation_id = {conv_id}')

    # 2. Connect via Socket.IO
    sio = socketio.AsyncClient(logger=False)
    events_received = []
    connected = asyncio.Event()

    @sio.event
    async def connect():
        print('[SOCKET] Connected!')
        connected.set()

    @sio.event
    async def connect_error(data):
        print(f'[SOCKET] Connect error: {data}')
        connected.set()

    @sio.event
    async def disconnect(reason):
        print(f'[SOCKET] Disconnected: {reason}')

    @sio.on('app_event')
    async def on_app_event(data):
        event_type = (
            data.get('payload', {}).get('type') if isinstance(data, dict) else '?'
        )
        print(
            f'[EVENT] id={data.get("id")} type={event_type}: {json.dumps(data)[:200]}'
        )
        events_received.append(data)

    @sio.on('*')
    async def catch_all(event, data):
        print(f'[SOCKET RAW] event={event} data={str(data)[:200]}')

    print(f'\n[INFO] Connecting socket to {BASE}...')
    try:
        await sio.connect(
            BASE,
            socketio_path='socket.io',
            transports=['websocket'],
            headers={},
            auth={},
            wait_timeout=10,
        )
    except Exception as e:
        print(f'[SOCKET] Initial connect failed (expected, no conv_id): {e}')

    # Reconnect with conversation_id
    await asyncio.sleep(0.5)
    print(f'[INFO] Connecting with conversation_id={conv_id}...')
    try:
        await sio.connect(
            f'{BASE}?conversation_id={conv_id}&latest_event_id=-1',
            socketio_path='socket.io',
            transports=['websocket'],
            auth={},
            wait_timeout=10,
        )
    except Exception as e:
        print(f'[SOCKET] Connect error: {e}')
        return

    await asyncio.wait_for(connected.wait(), timeout=10)
    print(f'[INFO] Socket connected={sio.connected}')

    # 3. Send a user message
    print("\n[INFO] Sending user message 'say hello'...")
    await sio.emit(
        'app_user_action',
        {
            'action': 'message',
            'args': {'content': 'say hello', 'image_urls': []},
        },
    )

    # 4. Wait for agent response
    print('[INFO] Waiting up to 30s for agent events...\n')
    await asyncio.sleep(30)

    print(f'\n[SUMMARY] Total events received: {len(events_received)}')
    for ev in events_received:
        t = ev.get('payload', {}).get('type', '?')
        print(f'  event id={ev.get("id")} type={t}')

    await sio.disconnect()


@pytest.mark.integration
async def test_full_e2e_trace():
    """Full e2e trace: create conversation, connect socket, send message, wait for agent."""
    await _run_e2e_trace()
