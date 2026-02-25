"""Socket test using AsyncSimpleClient for proper async event handling."""
import asyncio
import urllib.request
import json
import sys


def create_conv():
    req = urllib.request.Request(
        "http://localhost:3000/api/v1/conversations",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read())
    cid = d.get("conversation_id") or d.get("id")
    print(f"Conv status: {d.get('status')} id: {cid}")
    return cid


async def main():
    import socketio

    events = []
    conv_id = create_conv()

    sio = socketio.AsyncSimpleClient()

    await sio.connect(
        f"http://localhost:3000?conversation_id={conv_id}&latest_event_id=-1",
        socketio_path="/socket.io",
        transports=["websocket"],
        wait_timeout=10,
    )
    print(f"Connected SID: {sio.sid}")

    for i in range(8):
        try:
            event = await asyncio.wait_for(sio.receive(), timeout=2.0)
            name = event[0]
            data = str(event[1])[:200] if len(event) > 1 else ""
            print(f"EVENT [{i}]: name={name!r} data={data}")
            events.append(event)
        except asyncio.TimeoutError:
            print(f"  (timeout on attempt {i+1})")

    await sio.disconnect()
    forge_events = [e for e in events if e[0] == "forge_event"]
    print(f"\nTotal events: {len(events)}, forge_events: {len(forge_events)}")
    if forge_events:
        print("SUCCESS")
        sys.exit(0)
    else:
        print("FAIL")
        sys.exit(1)


asyncio.run(main())
