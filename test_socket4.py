"""Quick socket test with hardcoded fresh conversation ID."""
import asyncio
import socketio
import sys
import urllib.request
import json

# Create a fresh conversation
url = "http://localhost:3000/api/v1/conversations"
req = urllib.request.Request(url, data=b'{}', headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=5) as resp:
    data = json.loads(resp.read())
    
CONVERSATION_ID = data["conversation_id"]
BASE_URL = "http://localhost:3000"
CONNECT_URL = f"{BASE_URL}?conversation_id={CONVERSATION_ID}&latest_event_id=-1"

sys.stderr.write(f"Created conversation: {CONVERSATION_ID}\n")
sys.stderr.write(f"Connect URL: {CONNECT_URL}\n")

events_received = []

async def main():
    sio = socketio.AsyncClient(logger=False, engineio_logger=False)

    @sio.event
    async def connect():
        sys.stderr.write(f"Connected! sid={sio.get_sid()}\n")

    @sio.event
    async def disconnect():
        sys.stderr.write("Disconnected\n")

    @sio.on("forge_event")
    async def on_forge_event(data):
        obs = data.get("observation", "?") if isinstance(data, dict) else "?"
        sys.stderr.write(f"FORGE_EVENT: obs={obs} data_keys={list(data.keys()) if isinstance(data, dict) else data}\n")
        events_received.append(data)

    @sio.on("*")
    async def catch_all(event, data):
        sys.stderr.write(f"OTHER EVENT: {event} = {str(data)[:100]}\n")

    try:
        await sio.connect(
            CONNECT_URL,
            transports=["websocket", "polling"],
            socketio_path="/socket.io",
            wait_timeout=10,
        )
        sys.stderr.write("Waiting 8s for events...\n")
        await asyncio.sleep(8)
    except Exception as e:
        sys.stderr.write(f"EXCEPTION: {type(e).__name__} {e}\n")
    finally:
        await sio.disconnect()
        sys.stderr.write(f"Total forge_events received: {len(events_received)}\n")
        if events_received:
            sys.stderr.write("SUCCESS - socket is working!\n")
        else:
            sys.stderr.write("FAIL - no forge_events received\n")

asyncio.run(main())
