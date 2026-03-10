"""
audit_webapp.py — Full agentic-flow audit with a single vague sentence.

Tracks:
  - Every file the agent creates / modifies
  - Live creation timeline
  - Agent event stream (tool calls, observations)
  - Final file tree with line counts + full content
"""

from __future__ import annotations

import asyncio
import glob
import os
import sys
import time
from pathlib import Path

import httpx

from tui.client import ForgeClient

# ─── ONE-SENTENCE VAGUE PROMPT ───────────────────────────────────────────────
PROMPT = (
    "Build a task management web app where users can register, log in, "
    "create tasks with priorities and due dates, and mark them as done."
)
# ─────────────────────────────────────────────────────────────────────────────

BASE           = "http://127.0.0.1:3000"
POLL_INTERVAL  = 5     # seconds between /files/git/changes polls
MAX_POLL_TIME  = 600   # 10 minutes total
IDLE_THRESHOLD = 90    # stop if no new files for this many seconds
PREVIEW_LINES  = 80    # lines to show per file in audit


# ─── helpers ─────────────────────────────────────────────────────────────────

async def fetch_changes(client: httpx.AsyncClient, conv_id: str) -> list[dict]:
    url = f"{BASE}/api/v1/conversations/{conv_id}/files/git/changes"
    try:
        r = await client.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data if isinstance(data, list) else data.get("changes", [])
    except Exception:
        pass
    return []


def get_workspace_path(conv_id: str | None = None) -> str | None:
    """Find the active Forge workspace directory.

    First tries an exact conv_id match; if that fails (common when the server
    reuses a runtime from a previous session), falls back to the most recently
    modified FORGE_workspace_* directory.
    """
    base_temp = os.environ.get("TEMP", r"C:\Users\GIGABYTE\AppData\Local\Temp")
    if conv_id:
        exact = glob.glob(os.path.join(base_temp, f"FORGE_workspace_{conv_id}*"))
        if exact:
            return exact[0]
    # Fallback: most recently modified workspace dir
    all_ws = glob.glob(os.path.join(base_temp, "FORGE_workspace_*"))
    if all_ws:
        return max(all_ws, key=os.path.getmtime)
    return None


def read_file(ws_path: str, rel_path: str) -> str:
    full = os.path.join(ws_path, rel_path.replace("/", os.sep))
    if os.path.exists(full):
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            pass
    return ""


# ─── audit output ────────────────────────────────────────────────────────────

def print_audit(conv_id: str, files: dict[str, str], elapsed: float,
                agent_msgs: list[str]) -> None:
    ws_path = get_workspace_path(conv_id)

    print("\n\n" + "═" * 72)
    print("  FORGE AGENTIC FLOW — AUDIT REPORT")
    print("═" * 72)
    print(f"  Prompt  : \"{PROMPT}\"")
    print(f"  Time    : {elapsed:.0f}s")
    print(f"  Files   : {len(files)}")
    print(f"  Model   : gemini-3-flash-preview")
    print()

    # ── agent event timeline (brief) ─────────────────────────────────────────
    if agent_msgs:
        print("─" * 72)
        print("  AGENT EVENT LOG (last 30 events)")
        print("─" * 72)
        for line in agent_msgs[-30:]:
            print(f"  {line}")
        print()

    # ── file tree ─────────────────────────────────────────────────────────────
    print("─" * 72)
    print("  FILE TREE")
    print("─" * 72)
    by_dir: dict[str, list[str]] = {}
    for p in sorted(files):
        d = str(Path(p).parent)
        by_dir.setdefault(d, []).append(p)
    for d, paths in sorted(by_dir.items()):
        print(f"  {d}/")
        for p in sorted(paths):
            rel = Path(p).name
            if ws_path:
                content = read_file(ws_path, p)
                lc = len(content.splitlines())
                print(f"      {rel:<40s}  {lc:4d} lines  [{files[p]}]")
            else:
                print(f"      {rel}")
    print()

    # ── content ───────────────────────────────────────────────────────────────
    total_lines = 0
    for path in sorted(files):
        content = read_file(ws_path, path) if ws_path else ""
        lines = content.splitlines()
        total_lines += len(lines)

        print("─" * 72)
        print(f"  {path}  ({len(lines)} lines)")
        print("─" * 72)
        if lines:
            for ln in lines[:PREVIEW_LINES]:
                print(f"  {ln}")
            if len(lines) > PREVIEW_LINES:
                print(f"  ... [{len(lines) - PREVIEW_LINES} more lines omitted]")
        else:
            print("  (empty or unreadable)")
        print()

    print("═" * 72)
    print(f"  TOTAL: {len(files)} files · ~{total_lines} lines of code")
    print("═" * 72)


# ─── main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    # Server readiness check
    print("Checking Forge backend …")
    for _ in range(15):
        try:
            r = httpx.get(f"{BASE}/api/health/live", timeout=3)
            if r.status_code == 200:
                print("Server is up!\n")
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        print("Server not responding — aborting.")
        sys.exit(1)

    print("═" * 72)
    print("  FORGE FULL AGENTIC FLOW TEST")
    print("═" * 72)
    print(f"\n  Prompt (one sentence only):\n  \"{PROMPT}\"\n")

    forge = ForgeClient(BASE)
    agent_msgs: list[str] = []

    async def on_event(data: object) -> None:
        raw = str(data)
        # Summarise tool-call and observation events for the log
        for keyword in ("tool_call", "execute_bash", "str_replace_editor",
                        "think", "finish", "apply_patch", "structure_editor",
                        "action", "observation", "error", "warning"):
            if keyword in raw.lower():
                snippet = raw[:200].replace("\n", " ")
                agent_msgs.append(f"[{keyword.upper():<18s}] {snippet}")
                break

    forge._event_callback = on_event

    conv = await forge.create_conversation("task-management-webapp-audit")
    conv_id = (
        conv.get("conversation_id") if isinstance(conv, dict)
        else conv.conversation_id
    )
    print(f"  Conversation ID: {conv_id}\n")

    await forge.join_conversation(conv_id)
    await forge.send_message(PROMPT)
    await forge.start_agent(conv_id)

    print(f"  Agent running. Polling every {POLL_INTERVAL}s, "
          f"idle-stop at {IDLE_THRESHOLD}s, max {MAX_POLL_TIME}s …\n")

    found: dict[str, str] = {}   # path → git status
    last_new  = time.time()
    start     = time.time()

    async with httpx.AsyncClient() as http:
        while True:
            elapsed = time.time() - start
            if elapsed > MAX_POLL_TIME:
                print(f"\n[TIMEOUT] {MAX_POLL_TIME}s reached.")
                break

            changes = await fetch_changes(http, conv_id)
            for ch in changes:
                path   = (ch.get("path") or ch.get("file", "")).replace("\\", "/")
                status = ch.get("status", "?")
                if path and path not in found:
                    found[path] = status
                    last_new = time.time()
                    flag = {"A": "[+] CREATED", "M": "[~] MODIFIED",
                            "D": "[-] DELETED"}.get(status, f"[{status}]")
                    print(f"  {flag:<15s}  {path}")

            idle = time.time() - last_new
            print(
                f"  [{int(elapsed):5d}s elapsed | {len(found):3d} files | "
                f"idle {int(idle):3d}s / {IDLE_THRESHOLD}s]   ",
                end="\r",
            )

            if found and idle >= IDLE_THRESHOLD:
                print(f"\n\n  Agent appears done (no new files for {IDLE_THRESHOLD}s).")
                break

            await asyncio.sleep(POLL_INTERVAL)

    total_elapsed = time.time() - start

    if not found:
        print("\n[FAIL] Agent produced 0 files in the allotted time.")
        sys.exit(1)

    print_audit(conv_id, found, total_elapsed, agent_msgs)


if __name__ == "__main__":
    asyncio.run(main())
