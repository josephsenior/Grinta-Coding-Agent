"""
nextjs_audit.py — Full agentic-flow audit for a React/Next.js web app.

Tracks EVERY agent action from start to finish:
  - AgentThinkAction  (reasoning steps)
  - FileWriteAction   (file creates / edits)
  - CmdRunAction      (bash commands)
  - MessageAction     (agent messages)
  - All Observations  (command output, errors)
  - Circuit-breaker / pause events
  - Final file tree with content preview
"""

from __future__ import annotations

import asyncio
import glob
import os
import sys
import time
from pathlib import Path
from textwrap import shorten

import httpx

from tui.client import ForgeClient

# ─── PROMPT ──────────────────────────────────────────────────────────────────
PROMPT = (
    "Build a full-stack task management web app using Next.js 14 (App Router), "
    "TypeScript, Tailwind CSS, and SQLite (via better-sqlite3). "
    "Include: user registration and login with JWT auth, a dashboard showing all tasks, "
    "the ability to create tasks with a title, description, priority (low/medium/high), "
    "and due date, mark tasks as complete, and delete them. "
    "Use React Server Components for data fetching, API routes for mutations, "
    "and client components only where interactivity is needed. "
    "Create a proper project structure: app/, components/, lib/, types/, "
    "plus package.json, tsconfig.json, tailwind.config.ts, and a README."
)
# ─────────────────────────────────────────────────────────────────────────────

BASE            = "http://127.0.0.1:3000"
POLL_INTERVAL   = 4      # seconds between event-stream polls
MAX_POLL_TIME   = 900    # 15 minutes max
IDLE_THRESHOLD  = 120    # stop after 120s of no new events
PREVIEW_LINES   = 60     # lines to show per file in audit
EVENT_FETCH_MAX = 100    # events per batch (API max)

# ─── event type display mapping ──────────────────────────────────────────────
#   keys are substrings matched against event["action"] or event["observation"]
ACTION_LABELS: dict[str, str] = {
    "think":        "🧠 THINK",
    "message":      "💬 MSG  ",
    "run":          "⚡ RUN  ",
    "write":        "📝 WRITE",
    "read":         "📖 READ ",
    "browse":       "🌐 BROWSE",
    "finish":       "✅ FINISH",
    "reject":       "🚫 REJECT",
    "delegate":     "→  DELEGATE",
    "pause":        "⏸  PAUSE",
}
OBS_LABELS: dict[str, str] = {
    "success":      "✔  OK   ",
    "error":        "✖  ERROR",
    "null":         "·  NULL ",
    "run":          "▶  OUTPUT",
    "browse":       "🌐 PAGE ",
}


def fmt_event(evt: dict) -> str | None:
    """Format a single event dict into a one-line string. Returns None to skip."""
    source = evt.get("source", "")
    etype  = str(evt.get("action") or evt.get("observation") or "").lower()
    eid    = evt.get("id", "?")
    ts     = evt.get("timestamp", "")[:19].replace("T", " ") if evt.get("timestamp") else ""

    # Determine label
    label = None
    check_map = ACTION_LABELS if evt.get("action") else OBS_LABELS
    for key, lbl in check_map.items():
        if key in etype:
            label = lbl
            break
    if label is None:
        label = f"   {etype[:8]:<8s}"

    # Pull meaningful content
    content = ""
    if "think" in etype:
        thought = evt.get("args", {}).get("thought", "")
        content = shorten(thought, 120, placeholder="…")
    elif "write" in etype or "read" in etype:
        path = evt.get("args", {}).get("path", evt.get("args", {}).get("file", ""))
        content = path
    elif "run" in etype and evt.get("action"):
        cmd = evt.get("args", {}).get("command", "")
        content = shorten(cmd, 100, placeholder="…")
    elif evt.get("observation") == "run":
        out = evt.get("content", "")
        content = shorten(str(out).replace("\n", " ↵ "), 120, placeholder="…")
    elif evt.get("observation") == "error":
        content = shorten(str(evt.get("content", "")), 120, placeholder="…")
    elif "message" in etype:
        content = shorten(str(evt.get("args", {}).get("content", evt.get("content", ""))), 120, placeholder="…")
    elif "finish" in etype:
        content = shorten(str(evt.get("args", {}).get("outputs", {}).get("content", "")), 100, placeholder="…")
    else:
        # Generic fallback — grab content or args summary
        raw = evt.get("content") or evt.get("args") or {}
        content = shorten(str(raw).replace("\n", " "), 100, placeholder="…")

    prefix = f"[{eid:>4}] {ts}  {label}  "
    return prefix + content


# ─── helpers ─────────────────────────────────────────────────────────────────

async def fetch_events(
    client: httpx.AsyncClient,
    conv_id: str,
    start_id: int,
) -> tuple[list[dict], bool]:
    """Fetch a page of events starting from start_id. Returns (events, has_more)."""
    url = f"{BASE}/api/v1/conversations/{conv_id}/events"
    try:
        r = await client.get(url, params={
            "start_id": start_id,
            "limit": EVENT_FETCH_MAX,
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            events = data.get("events", [])
            has_more = data.get("has_more", False)
            return events, has_more
    except Exception as exc:
        print(f"\n  [WARN] events fetch failed: {exc}")
    return [], False


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
    base_temp = os.environ.get("TEMP", r"C:\Users\GIGABYTE\AppData\Local\Temp")
    if conv_id:
        exact = glob.glob(os.path.join(base_temp, f"FORGE_workspace_{conv_id}*"))
        if exact:
            return exact[0]
    all_ws = glob.glob(os.path.join(base_temp, "FORGE_workspace_*"))
    if all_ws:
        return max(all_ws, key=os.path.getmtime)
    return None


def read_ws_file(ws_path: str, rel_path: str) -> str:
    full = os.path.join(ws_path, rel_path.replace("/", os.sep))
    if os.path.exists(full):
        try:
            with open(full, encoding="utf-8", errors="replace") as f:
                return f.read()
        except Exception:
            pass
    return ""


# ─── final report ────────────────────────────────────────────────────────────

def print_report(
    conv_id: str,
    all_events: list[dict],
    files: dict[str, str],
    elapsed: float,
) -> None:
    ws_path = get_workspace_path(conv_id)

    SEP  = "═" * 76
    SEP2 = "─" * 76

    print(f"\n\n{SEP}")
    print("  FORGE NEXT.JS AUDIT — FULL REPORT")
    print(SEP)
    print(f"  Prompt  : \"{PROMPT[:80]}…\"")
    print(f"  Time    : {elapsed:.0f}s")
    print(f"  Events  : {len(all_events)}")
    print(f"  Files   : {len(files)}")
    print()

    # ── action timeline ───────────────────────────────────────────────────────
    print(SEP2)
    print("  COMPLETE ACTION TIMELINE  (all events)")
    print(SEP2)
    for evt in all_events:
        line = fmt_event(evt)
        if line:
            print(f"  {line}")
    print()

    # ── event summary stats ───────────────────────────────────────────────────
    print(SEP2)
    print("  EVENT SUMMARY")
    print(SEP2)
    counts: dict[str, int] = {}
    for evt in all_events:
        key = str(evt.get("action") or evt.get("observation") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:<30s}  {v:>4d}")
    print()

    # ── file tree ─────────────────────────────────────────────────────────────
    print(SEP2)
    print("  FILE TREE")
    print(SEP2)
    by_dir: dict[str, list[str]] = {}
    for p in sorted(files):
        d = str(Path(p).parent)
        by_dir.setdefault(d, []).append(p)
    for d, paths in sorted(by_dir.items()):
        print(f"  {d}/")
        for p in sorted(paths):
            if ws_path:
                content = read_ws_file(ws_path, p)
                lc = len(content.splitlines())
                print(f"      {Path(p).name:<50s}  {lc:4d} lines  [{files[p]}]")
            else:
                print(f"      {Path(p).name}")
    print()

    # ── file content preview ──────────────────────────────────────────────────
    total_lines = 0
    for path in sorted(files):
        content = read_ws_file(ws_path, path) if ws_path else ""
        lines   = content.splitlines()
        total_lines += len(lines)

        print(SEP2)
        print(f"  {path}  ({len(lines)} lines)")
        print(SEP2)
        if lines:
            for ln in lines[:PREVIEW_LINES]:
                print(f"  {ln}")
            if len(lines) > PREVIEW_LINES:
                print(f"  … [{len(lines) - PREVIEW_LINES} more lines omitted]")
        else:
            print("  (empty or unreadable)")
        print()

    print(SEP)
    print(f"  TOTAL: {len(files)} files · ~{total_lines} lines")
    print(SEP)


# ─── main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    # ── server check ─────────────────────────────────────────────────────────
    print("Checking Forge backend …")
    for _ in range(20):
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

    print("═" * 76)
    print("  FORGE NEXT.JS FULL-STACK AUDIT")
    print("═" * 76)
    print(f"\n  Prompt:\n  \"{PROMPT}\"\n")

    forge = ForgeClient(BASE)

    conv = await forge.create_conversation("nextjs-task-app-audit")
    conv_id = (
        conv.get("conversation_id") if isinstance(conv, dict)
        else conv.conversation_id
    )
    print(f"  Conversation ID: {conv_id}\n")

    await forge.join_conversation(conv_id)
    await forge.send_message(PROMPT)
    await forge.start_agent(conv_id)

    print(f"  Agent started. Polling events every {POLL_INTERVAL}s …\n")
    print("─" * 76)

    all_events:   list[dict]   = []
    seen_ids:     set[int]     = set()
    found_files:  dict[str, str] = {}
    next_event_id = 0
    last_activity = time.time()
    start         = time.time()

    async with httpx.AsyncClient() as http:
        while True:
            elapsed = time.time() - start
            if elapsed > MAX_POLL_TIME:
                print(f"\n[TIMEOUT] {MAX_POLL_TIME}s reached.")
                break

            # ── drain new events ──────────────────────────────────────────────
            new_event_count = 0
            while True:
                events, has_more = await fetch_events(http, conv_id, next_event_id)
                for evt in events:
                    eid = evt.get("id")
                    if eid in seen_ids:
                        continue
                    seen_ids.add(eid)
                    all_events.append(evt)
                    new_event_count += 1
                    last_activity = time.time()
                    next_event_id = max(next_event_id, (eid or 0) + 1)

                    # Print event live
                    line = fmt_event(evt)
                    if line:
                        print(f"  {line}")

                if not has_more:
                    break

            # ── check new files ───────────────────────────────────────────────
            changes = await fetch_changes(http, conv_id)
            for ch in changes:
                path   = (ch.get("path") or ch.get("file", "")).replace("\\", "/")
                status = ch.get("status", "?")
                if path and path not in found_files:
                    found_files[path] = status
                    flag = {"A": "[+] CREATED", "M": "[~] MODIFIED",
                            "D": "[-] DELETED"}.get(status, f"[{status}]")
                    print(f"\n  {flag:<15s}  {path}")

            # ── status bar ───────────────────────────────────────────────────
            idle = time.time() - last_activity
            print(
                f"  [{int(elapsed):5d}s elapsed | {len(all_events):3d} events | "
                f"{len(found_files):3d} files | idle {int(idle):3d}s / {IDLE_THRESHOLD}s]   ",
                end="\r",
            )

            # ── idle-stop: only once we have some events ──────────────────────
            if all_events and idle >= IDLE_THRESHOLD:
                print(f"\n\n  Agent idle for {IDLE_THRESHOLD}s — stopping.")
                break

            await asyncio.sleep(POLL_INTERVAL)

    total_elapsed = time.time() - start

    if not all_events:
        print("\n[FAIL] No agent events observed.")
        sys.exit(1)

    print_report(conv_id, all_events, found_files, total_elapsed)


if __name__ == "__main__":
    asyncio.run(main())
