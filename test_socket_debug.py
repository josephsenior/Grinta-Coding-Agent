"""Debug socket.io polling protocol."""
import asyncio
import socketio
import sys


async def main():
    cid = "7f8f5b629b084c59aad575140a0ddf44"
    sio = socketio.AsyncClient(logger=True, engineio_logger=True)
    count = [0]

    @sio.on("forge_event")
    async def on_forge(data):
        count[0] += 1
        print(f"  [FORGE_EVENT] #{count[0]}: {str(data)[:200]}", flush=True)

    url = f"http://localhost:3000?conversation_id={cid}&latest_event_id=-1"
    print("Connecting...", flush=True)
    await sio.connect(
        url, socketio_path="socket.io", transports=["polling"], wait_timeout=10
    )
    print(f"Connected! sid={sio.get_sid()}", flush=True)
    await asyncio.sleep(8)
    print(f"forge_events received: {count[0]}", flush=True)
    await sio.disconnect()
    print("Done", flush=True)


asyncio.run(main())
