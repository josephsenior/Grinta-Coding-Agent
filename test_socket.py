"""Quick socket.io connectivity test."""
import asyncio
import socketio


async def main():
    cid = "7f8f5b629b084c59aad575140a0ddf44"
    sio = socketio.AsyncClient(logger=False)
    forge_events = []

    @sio.on("forge_event")
    async def on_forge(data):
        forge_events.append(data)
        obs = data.get("observation", "") if isinstance(data, dict) else ""
        eid = data.get("id", "?") if isinstance(data, dict) else "?"
        print(f"  forge_event #{len(forge_events)}: obs={obs!r} id={eid}")

    @sio.on("connect")
    def on_connect():
        print(">>> Socket connected")

    @sio.on("connect_error")
    def on_connect_error(err):
        print(">>> Connect error:", err)

    url = f"http://localhost:3000?conversation_id={cid}&latest_event_id=-1"
    print(f"Connecting to {url}")
    try:
        await sio.connect(
            url,
            socketio_path="socket.io",
            transports=["polling"],
            wait_timeout=15,
        )
        sid = sio.get_sid()
        print(f"Connected! My sid={sid}")
        print("Waiting 12 seconds for forge_events...")
        await asyncio.sleep(12)
        print(f"Total forge_events: {len(forge_events)}")
    except Exception as e:
        print(f"Exception during connect/wait: {e}")
    finally:
        await sio.disconnect()
        print("Disconnected. Done.")


asyncio.run(main())
