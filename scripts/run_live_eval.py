import subprocess
import time
import requests
import asyncio
import socketio
import json
import sys
import psutil

# 1. Kill old servers
for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        cmdline = " ".join(proc.info['cmdline'] or []).lower()
        if "uvicorn" in cmdline or "start_server.py" in cmdline or "forge.py" in cmdline:
            if sys.executable.lower() in cmdline or 'python' in cmdline:
                print(f"Killing old server process {proc.pid}")
                proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pass

# Wait a moment for ports to free
time.sleep(2)

print("Starting fresh live server...")
server_proc = subprocess.Popen([sys.executable, "start_server.py"], stdout=sys.stdout, stderr=sys.stderr)

print("Waiting for server to become healthy...")
# Try up to 30 times (60 seconds)
server_up = False
for _ in range(30):
    try:
        r = requests.get("http://127.0.0.1:3000/api/v1/health", timeout=5)
        if r.status_code == 200:
            server_up = True
            break
    except Exception:
        pass
    time.sleep(2)

if not server_up:
    print("FAILED TO START SERVER")
    server_proc.kill()
    sys.exit(1)

print("Server is UP! Running test scenario...")

async def run_scenario():
    sio = socketio.AsyncClient()
    
    print("Creating conversation HTTP POST...")
    res = requests.post("http://127.0.0.1:3000/api/v1/conversations", json={}, timeout=60)
    res.raise_for_status()
    conv = res.json()
    sid = conv["conversation_id"]
    print(f"Conversation defined: {sid}")

    @sio.event
    async def connect():
        print("WS Connected!")

    @sio.event
    async def disconnect():
        print("WS Disconnected!")

    events_seen = []
    
    @sio.on("forge_event")
    async def on_forge_event(data):
        events_seen.append(data)
        if "action" in data and data["action"] == "working_memory":
            print("\n----- MEMORY SCRATCHPAD UPDATE -----")
            print(json.dumps(data.get("args", {}), indent=2))
            print("------------------------------------")
        
        if data.get("type") == "observation" and "output" in data:
            print(f"> Tool Output: {str(data['output'])[:100]}...")

        if data.get("state") == "awaiting_user_input":
            print("Agent has finished execution.")
            await sio.disconnect()

    print("Connecting WS...")
    await sio.connect(f"http://127.0.0.1:3000?conversation_id={sid}&latest_event_id=-1")
    
    await asyncio.sleep(1)
    
    msg = "Create a Python script in a folder named `real_world_task` containing a script `app.py` that starts a tiny FastAPI server on port 8080 returning {'message': 'Hello World'}. Also write a `requirements.txt` for it in that folder. Use tool calls to write the files."
    print("Sending prompt...")
    await sio.emit("forge_user_action", {
        "action": "message",
        "args": {"content": msg, "image_urls": [], "file_urls": []}
    })
    
    try:
        await sio.wait()
    except asyncio.CancelledError:
        pass

asyncio.run(run_scenario())

print("Shutting down live server...")
server_proc.terminate()
try:
    server_proc.wait(timeout=5)
except:
    server_proc.kill()
print("Done!")
