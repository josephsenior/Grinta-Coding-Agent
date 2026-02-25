"""Test socket connection using AsyncClient with event reception."""
import asyncio
import socketio
import sys

CONVERSATION_ID = ""
BASE_URL = "http://localhost:3000"
CONNECT_URL = f"{BASE_URL}?conversation_id={CONVERSATION_ID}&latest_event_id=-1"

events_received = []

async def main():
    sio = socketio.AsyncClient(logger=True, engineio_logger=True)

    @sio.event
    async def connect():
        sys.stderr.write(f"Connected! sid={sio.get_sid()}\n")

    @sio.event
    async def disconnect():
        sys.stderr.write("Disconnected\n")

    @sio.on("forge_event")
    async def on_forge_event(data):
        sys.stderr.write(f"forge_event received: {data}\n")
        events_received.append(data)

    @sio.on("*")
    async def catch_all(event, data):
        sys.stderr.write(f"catch_all event={event} data={data}\n")

    try:
        await sio.connect(
            CONNECT_URL,
            transports=["polling"],
            socketio_path="/socket.io",
            wait_timeout=10,
            headers={},
            namespaces=["/"],
        )
        sys.stderr.write("Waiting 15s for events...\n")
        await asyncio.sleep(15)
    except Exception as e:
        sys.stderr.write(f"EXCEPTION: {type(e).__name__} {e}\n")
    finally:
        await sio.disconnect()
        sys.stderr.write(f"Total forge_events received: {len(events_received)}\n")

asyncio.run(main())
