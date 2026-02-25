"""Test that forge_event is delivered over socket.io after MissingSettingsError fix."""
import urllib.request
import json
import time
import sys

import socketio

def create_conversation():
    req = urllib.request.Request(
        "http://localhost:3000/api/v1/conversations",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read())
    return d.get("conversation_id") or d.get("id")

def main():
    conv_id = create_conversation()
    print(f"conversation_id: {conv_id}")

    events = []
    sio = socketio.SimpleClient()
    url = f"http://localhost:3000?conversation_id={conv_id}&latest_event_id=-1"
    sio.connect(url, socketio_path="/socket.io", transports=["websocket"],
                namespace="/", wait_timeout=10)
    print(f"Connected SID: {sio.sid}")

    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            event = sio.receive(timeout=2)
            print(f"EVENT: {event[0]!r} data={str(event[1])[:100] if len(event)>1 else ''}")
            events.append(event)
        except Exception as e:
            remaining = deadline - time.time()
            if remaining > 0:
                print(f"  (waiting {remaining:.0f}s more...)")
            else:
                break

    sio.disconnect()
    print(f"\nTotal forge_events: {sum(1 for e in events if e[0] == 'forge_event')}")
    if any(e[0] == "forge_event" for e in events):
        print("SUCCESS - forge_event received!")
        sys.exit(0)
    else:
        print("FAIL - no forge_event received")
        sys.exit(1)

if __name__ == "__main__":
    main()
