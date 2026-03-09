"""
complex_audit5.py — Full CRUD REST API with JWT auth (multi-file agent task).

Task: Build a FastAPI CRUD app with JWT authentication across 5 real files.
Pass: all 5 target files detected in git/changes AND each has non-empty content.
"""

import asyncio
from tui.client import ForgeClient
import time
import httpx
import os
import glob

# Files the agent must create (relative paths inside the workspace)
REQUIRED_FILES = {
    "auth_api/main.py",
    "auth_api/models.py",
    "auth_api/auth.py",
    "auth_api/routes/users.py",
    "auth_api/requirements.txt",
}

TASK_PROMPT = """\
Build a FastAPI REST API project in a folder called 'auth_api'. The project must contain exactly these files with real, working code:

1. auth_api/main.py
   - FastAPI app instance
   - Include router from routes/users.py
   - POST /auth/login endpoint: accepts {"username": str, "password": str}, validates against a hardcoded user list in models.py, returns {"access_token": str, "token_type": "bearer"}
   - Use python-jose to generate a JWT token (HS256, secret key = "SUPERSECRET", expire in 30 min)

2. auth_api/models.py
   - Pydantic BaseModel: User(id: int, username: str, password: str, email: str)
   - Pydantic BaseModel: UserOut(id: int, username: str, email: str)  (no password)
   - In-memory list USERS with 3 hardcoded User objects

3. auth_api/auth.py
   - decode_token(token: str) -> dict: decodes JWT, raises HTTPException 401 if invalid
   - get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut: uses decode_token

4. auth_api/routes/users.py
   - APIRouter with prefix="/users"
   - GET /users/me — returns current user (protected, depends on get_current_user)
   - GET /users/ — returns list of all UserOut (protected)
   - PUT /users/{user_id} — update email of a user by id (protected), returns updated UserOut
   - DELETE /users/{user_id} — delete user by id (protected), returns {"deleted": user_id}

5. auth_api/requirements.txt
   - fastapi, uvicorn, python-jose[cryptography], passlib[bcrypt], pydantic

Write complete, working Python code in every file. Import everything correctly.
"""

POLL_INTERVAL = 5       # seconds between /git/changes polls
MAX_WAIT = 240          # total seconds to wait for all files


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
        if '"source": "agent"' in msg or "agent" in msg.lower():
            snippet = msg[:220].replace("\n", " ")
            print(f"  [Agent] {snippet}")

    client._event_callback = on_event

    conv = await client.create_conversation("CRUD REST API with JWT auth")
    conv_id = conv.get("conversation_id") if isinstance(conv, dict) else conv.conversation_id
    print(f"\nConversation ID: {conv_id}")

    await client.join_conversation(conv_id)
    print("Joined WebSocket.\n")

    print(">>> Sending task prompt to agent...\n")
    print(TASK_PROMPT)
    await client.send_message(TASK_PROMPT)
    await client.start_agent(conv_id)
    print("\nAgent started. Polling /git/changes every 5s for up to 240s...\n")

    start_time = time.time()
    found_files: dict[str, dict] = {}
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
                    norm = path.replace("\\", "/")
                    if norm not in found_files:
                        found_files[norm] = change
                        print(f"  [+] New file detected: {norm}  (status={change.get('status', '?')})")

                elapsed = int(time.time() - start_time)
                missing = REQUIRED_FILES - found_files.keys()
                print(f"  [{elapsed:3d}s] {len(found_files)} file(s) detected. Still waiting for: {missing or 'nothing!'}")

                if REQUIRED_FILES.issubset(found_files.keys()):
                    success = True
                    break

            except Exception as e:
                print(f"  [!] Poll error: {e}")

    print("\n" + "=" * 60)
    if success:
        elapsed_total = int(time.time() - start_time)
        print(f"[SUCCESS] All 5 required files created in {elapsed_total}s!\n")
        ws_path = get_workspace_path(conv_id)
        for rel_path in sorted(REQUIRED_FILES):
            print(f"\n{'='*50}\n--- {rel_path} ---\n{'='*50}")
            if ws_path:
                content = read_file_content(ws_path, rel_path)
                if content.strip():
                    print(content)
                else:
                    print("  (file is empty or could not be read from workspace)")
            else:
                print("  (workspace path not found locally)")
    else:
        print("[FAILED] Agent did not produce all required files within the timeout.\n")
        print("Files detected so far:")
        for p in sorted(found_files.keys()):
            print(f"  - {p}")
        print("\nMissing:")
        for p in sorted(REQUIRED_FILES - found_files.keys()):
            print(f"  - {p}")


if __name__ == "__main__":
    asyncio.run(main())
