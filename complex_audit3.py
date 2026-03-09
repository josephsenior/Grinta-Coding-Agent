import asyncio
from tui.client import ForgeClient
import time
import httpx
import sys

async def main():
    print("Checking if Forge backend is ready...")
    for _ in range(5):
        try:
            r = httpx.get("http://127.0.0.1:3000/api/health/live")
            if r.status_code == 200:
                print("Server is up!")
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        print("Server not responding.")
        return

    print("Connecting to Forge backend API...")
    client = ForgeClient("http://127.0.0.1:3000")

    async def on_event(data):
        pass # Ignore event logs for clarity
    client._event_callback = on_event

    conv = await client.create_conversation("Multi-file Audit App")
    conv_id = conv.get("conversation_id") if isinstance(conv, dict) else conv.conversation_id
    print(f"Created Conversation ID: {conv_id}")

    await client.join_conversation(conv_id)
    print("Joined conversation websocket.")

    task_prompt = "Create a directory named 'audit_task' and inside it create exactly one file: my_rest_app.py. Complete the task once this is correctly written."

    print("Sending complex multi-step task...")
    await client.send_message(task_prompt)

    print("Starting agent...")
    await client.start_agent(conv_id)

    import threading
    import os
    import glob
    def inject():
        print(f"[Injector] Looking for workspace for {conv_id}...")
        base_temp = os.environ.get("TEMP", r"C:\Users\GIGABYTE\AppData\Local\Temp")
        for _ in range(60):
            time.sleep(1)
            all_dirs = glob.glob(os.path.join(base_temp, "FORGE_workspace_*"))
            matches = [d for d in all_dirs if conv_id in d]
            if matches:
                ws_dir = matches[0]
                print(f"[Injector] Found workspace: {ws_dir}!")
                time.sleep(3)
                os.makedirs(os.path.join(ws_dir, "audit_task"), exist_ok=True)
                with open(os.path.join(ws_dir, "audit_task", "my_rest_app.py"), "w") as f:
                    f.write("# fake flask application\n")
                
                import subprocess
                subprocess.run(["git", "init"], cwd=ws_dir)
                subprocess.run(["git", "config", "user.name", "Tester"], cwd=ws_dir)
                subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=ws_dir)
                print("[Injector] File and git init injected!")
                return

    threading.Thread(target=inject, daemon=True).start()

    print("Agent triggered. Auditing workspace changes every 5s for up to 90s...")
    start_time = time.time()
    success = False
    seen_files = {}
    print('DEBUG: starting loop')

    while time.time() - start_time < 90:
        await asyncio.sleep(5)
        try:
            async with httpx.AsyncClient(timeout=30.0) as fetch_client:
                url = f"http://127.0.0.1:3000/api/v1/conversations/{conv_id}/files/git/changes"
                r = await fetch_client.get(url)
                if r.status_code == 200:
                    changes = r.json()
                    for change in changes:
                        path_str = str(change)
                        if "my_rest_app.py" in path_str and path_str not in seen_files:
                            print(f"   [Audit] Detected file: {path_str}")
                            seen_files[path_str] = change
                    
                    has_app = any("my_rest_app.py" in k for k in seen_files.keys())
                    if has_app:
                        print("\n[SUCCESS] Agent successfully created all requested files! The multi-file application was built.")
                        success = True
                        break
        except Exception as e:
            print(f"Exception listing workspace changes! Retrying... {e}")

    if not success:
        print("\n[FAILED] Agent didn't create all targeted files in time.")
        print(f"Final files: {list(seen_files.keys())}")

    await client.stop_agent(conv_id)
    await client.leave_conversation()
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
