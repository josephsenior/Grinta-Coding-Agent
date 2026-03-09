"""
complex_audit4.py — Multi-file agent task test (no injector, no "complete when done").

Task: Build a minimal Flask REST API project with real content across multiple files.
Pass: all 4 target files are detected in git/changes AND each has non-empty content.
"""

import asyncio
from tui.client import ForgeClient
import time
import httpx
import os
import glob

# Files the agent must create (relative paths inside the workspace)
REQUIRED_FILES = {
    "rest_api/app/main.py",
    "rest_api/app/models.py",
    "rest_api/requirements.txt",
    "rest_api/README.md",
}

TASK_PROMPT = """\
Build a minimal REST API project in a folder called 'rest_api'. The project must contain:

1. rest_api/app/main.py   — A Flask app with at least two routes: GET /health (returns {"status": "ok"}) and GET /users (returns a list of users from models.py).
2. rest_api/app/models.py — A User dataclass with fields: id (int), name (str), email (str). Include a small in-memory list of 2–3 sample users.
3. rest_api/requirements.txt — Python dependencies (flask, at minimum).
4. rest_api/README.md — A short description of the project and how to run it.

Write real, working code in every file. Do not leave any file empty.
"""

POLL_INTERVAL = 5       # seconds between /git/changes polls
MAX_WAIT = 180          # total seconds to wait for all files


async def fetch_changes(client: httpx.AsyncClient, conv_id: str) -> list:
    url = f"http://127.0.0.1:3000/api/v1/conversations/{conv_id}/files/git/changes"
    r = await client.get(url)
    if r.status_code == 200:
        return r.json()
    return []


def get_workspace_path(conv_id: str) -> str | None:
    base_temp = os.environ.get("TEMP", r"C:\Users\GIGABYTE\AppData\Local\Temp")
    matches = glob.glob(os.path.join(base_temp, f"FORGE_workspace_{conv_id}*"))
    return matches[0] if matches else None


def read_file_content(ws_path: str, rel_path: str) -> str:
    full = os.path.join(ws_path, rel_path.replace("/", os.sep))
    if os.path.exists(full):
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    return ""


async def main():
    print("Checking if Forge backend is ready...")
    for _ in range(10):
        try:
            r = httpx.get("http://127.0.0.1:3000/api/health/live", timeout=3)
            if r.status_code == 200:
                print("Server is up!")
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        print("Server not responding after 10s — aborting.")
        return

    client = ForgeClient("http://127.0.0.1:3000")

    ws_events = []
    async def on_event(data):
        msg = str(data)
        ws_events.append(msg)
        # Print agent messages so we can follow along
        if '"source": "agent"' in msg or "agent" in msg.lower():
            print(f"  [Agent] {msg[:200]}")

    client._event_callback = on_event

    conv = await client.create_conversation("Complex Multi-File REST API")
    conv_id = conv.get("conversation_id") if isinstance(conv, dict) else conv.conversation_id
    print(f"\nConversation ID: {conv_id}")

    await client.join_conversation(conv_id)
    print("Joined WebSocket.\n")

    print(">>> Sending task prompt to agent...\n")
    print(TASK_PROMPT)
    await client.send_message(TASK_PROMPT)
    await client.start_agent(conv_id)
    print("Agent started. Polling /git/changes every 5s for up to 180s...\n")

    start_time = time.time()
    found_files: dict[str, dict] = {}   # rel_path -> change dict
    success = False

    async with httpx.AsyncClient(timeout=30.0) as http:
        while time.time() - start_time < MAX_WAIT:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                changes = await fetch_changes(http, conv_id)
                for change in changes:
                    path = change.get("path", "")
                    if not path:
                        continue
                    # Normalize slashes for comparison
                    norm = path.replace("\\", "/")
                    if norm not in found_files:
                        found_files[norm] = change
                        print(f"  [+] New file detected: {norm}  (status={change.get('status', '?')})")

                elapsed = int(time.time() - start_time)
                have = {p for p in found_files if any(p.endswith(r.split("/")[-1]) and r.split("/")[0] in p for r in REQUIRED_FILES)}
                missing = REQUIRED_FILES - found_files.keys()
                print(f"  [{elapsed:3d}s] {len(found_files)} file(s) detected. Still waiting for: {missing or 'nothing!'}")

                if REQUIRED_FILES.issubset(found_files.keys()):
                    success = True
                    break

            except Exception as e:
                print(f"  [!] Poll error: {e}")

    print("\n" + "="*60)
    if success:
        print("[SUCCESS] All required files were created by the agent!\n")
        ws_path = get_workspace_path(conv_id)
        for rel_path in sorted(REQUIRED_FILES):
            print(f"\n--- {rel_path} ---")
            if ws_path:
                content = read_file_content(ws_path, rel_path)
                if content.strip():
                    print(content)
                else:
                    print("  (file is empty or could not be read)")
            else:
                print("  (workspace path not found locally)")
    else:
        print("[FAILED] Agent did not produce all required files in time.\n")
        print("Files detected:")
        for p in sorted(found_files.keys()):
            print(f"  - {p}")
        print("Missing:")
        for p in sorted(REQUIRED_FILES - found_files.keys()):
            print(f"  - {p}")
    print("="*60)

    await client.stop_agent(conv_id)
    await client.leave_conversation()
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
