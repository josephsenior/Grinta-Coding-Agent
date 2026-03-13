#!/usr/bin/env python3
"""
Test that the task_tracker tool is actually used by the Forge agent
on multi-step tasks.

Usage:
    1. Start the server:  $env:FORGE_WATCH="0"; python start_server.py
    2. Run this script:   python test_task_tracker.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE = os.environ.get("FORGE_BASE_URL", "http://127.0.0.1:3000")
POLL_INTERVAL = 3
READY_TIMEOUT = 120
TASK_TIMEOUT = 300


# ── Helpers ──────────────────────────────────────────────────────────────────

def api(method: str, path: str, body=None, ct: str = "application/json"):
    url = BASE + path
    if ct == "application/json" and body is not None:
        data = json.dumps(body).encode()
    elif body is not None:
        data = body.encode()
    else:
        data = None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": ct},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}
    except Exception as e:
        return {"error": str(e)}


def wait_for_state(cid: str, target_states: set[str], timeout: int) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        resp = api("GET", f"/api/v1/conversations/{cid}")
        state = resp.get("agent_state", "unknown")
        if state in target_states:
            return state
        time.sleep(POLL_INTERVAL)
    return "timeout"


def collect_events(cid: str) -> list[dict]:
    all_events = []
    start_id = 0
    while True:
        resp = api("GET", f"/api/v1/conversations/{cid}/events?start_id={start_id}&limit=50")
        events = resp.get("events", [])
        if not events:
            break
        all_events.extend(events)
        start_id = events[-1].get("id", start_id) + 1
        if not resp.get("has_more", False):
            break
    return all_events


def extract_task_tracker_events(events: list[dict]) -> list[dict]:
    """Find all task_tracking action events."""
    tt_events = []
    for ev in events:
        action = ev.get("action", "")
        # Check for task_tracking action type
        if action == "task_tracking":
            tt_events.append(ev)
        # Also check for tool calls to "task_tracker"
        args = ev.get("args", {})
        if args.get("tool_name") == "task_tracker" or args.get("name") == "task_tracker":
            tt_events.append(ev)
    return tt_events


def extract_answer_and_tools(events: list[dict]) -> tuple[str, list[str]]:
    answer_parts = []
    tools = []
    for ev in events:
        action = ev.get("action", "")
        args = ev.get("args", {})

        if action == "message" and ev.get("source") == "agent":
            content = args.get("content", "") or ev.get("message", "")
            if content:
                answer_parts.append(content)
        elif action == "think":
            content = args.get("content", "")
            if content:
                answer_parts.append(f"[think] {content}")

        if action == "finish":
            content = args.get("outputs", {}).get("content", "") or args.get("content", "")
            thought = args.get("thought", "")
            if content:
                answer_parts.append(content)
            if thought:
                answer_parts.append(f"[finish-thought] {thought}")

        if action in ("run", "read", "browse", "write", "edit", "task_tracking"):
            cmd = args.get("command", "") or args.get("path", "") or action
            tools.append(f"{action}: {cmd[:80]}")

    return "\n".join(answer_parts), tools


def check_keywords(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    lower = text.lower()
    hits = [k for k in keywords if k.lower() in lower]
    misses = [k for k in keywords if k.lower() not in lower]
    return hits, misses


# ── Task Definitions ─────────────────────────────────────────────────────────

TASKS = [
    {
        "name": "Multi-step file creation",
        "prompt": (
            "Create a simple Python calculator package with the following files:\n"
            "1. calc/__init__.py - package init that exports Calculator class\n"
            "2. calc/calculator.py - Calculator class with add, subtract, multiply, divide methods\n"
            "3. calc/test_calculator.py - unit tests using pytest for all 4 operations\n"
            "4. calc/README.md - brief documentation explaining how to use the calculator\n"
            "5. calc/setup.py - basic setuptools configuration\n\n"
            "Create all 5 files. Use the task_tracker tool to track your progress."
        ),
        "success_keywords": ["calculator", "add", "subtract", "multiply", "divide"],
        "expect_task_tracker": True,
        "min_files": 4,
    },
    {
        "name": "Multi-step analysis",
        "prompt": (
            "Analyze this project's codebase and create a comprehensive report. Do these steps:\n"
            "1. First, examine the project structure and identify the main components\n"
            "2. Then, read the key configuration files (settings.json, pyproject.toml)\n"
            "3. Next, identify the LLM integration approach by reading backend/llm/ files\n"
            "4. Finally, summarize the architecture in a clear, structured format\n\n"
            "Track your progress with the task_tracker tool as you complete each step."
        ),
        "success_keywords": ["backend", "frontend", "llm", "python"],
        "expect_task_tracker": True,
        "min_files": 0,
    },
]


# ── Main ─────────────────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    name: str
    status: str = "not_run"
    duration_s: float = 0.0
    events: list = field(default_factory=list)
    answer_text: str = ""
    tools_used: list = field(default_factory=list)
    task_tracker_events: list = field(default_factory=list)
    keyword_hits: list = field(default_factory=list)
    keyword_misses: list = field(default_factory=list)
    files_created: int = 0
    error: str = ""


def run_task(task: dict) -> TaskResult:
    result = TaskResult(name=task["name"])
    print(f"\n{'='*60}")
    print(f"TASK: {task['name']}")
    print(f"{'='*60}")
    print(f"Prompt: {task['prompt'][:120]}...")

    # Create conversation
    resp = api("POST", "/api/v1/conversations", {})
    cid = resp.get("conversation_id")
    if not cid:
        result.status = "error"
        result.error = f"Failed to create conversation: {resp}"
        print(f"  ERROR: {result.error}")
        return result
    print(f"  Conversation: {cid}")

    # Wait for runtime
    print(f"  Waiting for runtime ready...")
    state = wait_for_state(cid, {"awaiting_user_input"}, READY_TIMEOUT)
    if state == "timeout":
        result.status = "timeout"
        result.error = "Runtime did not become ready"
        print(f"  TIMEOUT waiting for ready state")
        return result
    print(f"  Runtime ready!")

    # Send task
    t0 = time.time()
    resp = api("POST", f"/api/v1/conversations/{cid}/events/raw",
               body=task["prompt"], ct="text/plain")
    if "error" in resp:
        result.status = "error"
        result.error = f"Send failed: {resp}"
        print(f"  ERROR sending: {resp}")
        return result
    print(f"  Task sent. Polling...")

    # Poll for completion
    final_state = wait_for_state(
        cid,
        {"awaiting_user_input", "finished", "stopped", "error"},
        TASK_TIMEOUT,
    )
    result.duration_s = time.time() - t0

    if final_state == "timeout":
        result.status = "timeout"
        result.error = f"Agent did not finish within {TASK_TIMEOUT}s"
        print(f"  TIMEOUT after {result.duration_s:.1f}s")
    elif final_state == "error":
        result.status = "error"
        result.error = "Agent ended in error state"
        print(f"  ERROR after {result.duration_s:.1f}s")
    else:
        print(f"  Completed in {result.duration_s:.1f}s (state={final_state})")

    # Collect events
    result.events = collect_events(cid)
    result.answer_text, result.tools_used = extract_answer_and_tools(result.events)
    result.task_tracker_events = extract_task_tracker_events(result.events)

    # Count file writes
    for ev in result.events:
        if ev.get("action") in ("write",):
            result.files_created += 1

    # Keyword check
    combined_text = result.answer_text
    for ev in result.events:
        for key in ("observation", "content", "message"):
            val = ev.get(key, "") or ev.get("args", {}).get(key, "")
            if val:
                combined_text += "\n" + str(val)

    result.keyword_hits, result.keyword_misses = check_keywords(
        combined_text, task.get("success_keywords", [])
    )

    if final_state not in ("timeout", "error"):
        if result.keyword_misses:
            result.status = "partial"
        else:
            result.status = "passed"

    # Print summary
    print(f"\n  --- Result ---")
    print(f"  Status: {result.status}")
    print(f"  Duration: {result.duration_s:.1f}s")
    print(f"  Events: {len(result.events)}")
    print(f"  Tools used: {len(result.tools_used)}")
    for t in result.tools_used[:8]:
        print(f"    - {t}")
    if len(result.tools_used) > 8:
        print(f"    ... and {len(result.tools_used)-8} more")

    # Task tracker details
    print(f"\n  --- Task Tracker ---")
    print(f"  Task tracker events: {len(result.task_tracker_events)}")
    for tt in result.task_tracker_events:
        args = tt.get("args", {})
        cmd = args.get("command", "?")
        task_list = args.get("task_list", [])
        print(f"    [{cmd}] {len(task_list)} tasks")
        for t in task_list[:5]:
            desc = t.get("description", t.get("title", "?"))
            status = t.get("status", "?")
            print(f"      - [{status}] {desc[:60]}")

    if task.get("expect_task_tracker") and not result.task_tracker_events:
        print(f"  WARNING: Expected task_tracker usage but none found!")
        if result.status == "passed":
            result.status = "partial"

    print(f"\n  Keywords hit: {result.keyword_hits}")
    if result.keyword_misses:
        print(f"  Keywords MISSED: {result.keyword_misses}")
    if task.get("min_files") and result.files_created < task["min_files"]:
        print(f"  WARNING: Expected >= {task['min_files']} files but got {result.files_created}")

    # Answer preview
    if result.answer_text:
        preview = result.answer_text[:400]
        print(f"\n  --- Answer preview ---")
        for line in preview.split("\n")[:10]:
            print(f"  | {line}")
        if len(result.answer_text) > 400:
            print(f"  | ... ({len(result.answer_text)} chars total)")

    return result


def main():
    print(f"Checking server at {BASE}...")
    try:
        resp = api("GET", "/api/v1/conversations")
        if isinstance(resp.get("error"), int) and resp["error"] >= 500:
            print(f"Server error: {resp}")
            print(f"Start: $env:FORGE_WATCH='0'; python start_server.py")
            sys.exit(1)
    except Exception as e:
        print(f"Server not reachable: {e}")
        print(f"Start: $env:FORGE_WATCH='0'; python start_server.py")
        sys.exit(1)
    print("Server is up!\n")

    results: list[TaskResult] = []
    for task in TASKS:
        try:
            r = run_task(task)
            results.append(r)
        except Exception as e:
            r = TaskResult(name=task["name"], status="error", error=str(e))
            results.append(r)
            print(f"  EXCEPTION: {e}")

    # Final report
    print(f"\n\n{'='*60}")
    print(f"TASK TRACKER TEST REPORT")
    print(f"{'='*60}")

    passed = sum(1 for r in results if r.status == "passed")
    partial = sum(1 for r in results if r.status == "partial")
    failed = sum(1 for r in results if r.status in ("failed", "error", "timeout"))

    print(f"\nResults: {passed}/{len(results)} passed, {partial} partial, {failed} failed\n")

    for r in results:
        icon = {"passed": "OK", "partial": "~~", "timeout": "TO", "error": "!!"}.get(r.status, "??")
        tt_count = len(r.task_tracker_events)
        print(
            f"  [{icon}] {r.name:<30} {r.duration_s:6.1f}s  "
            f"events={len(r.events):<4} tools={len(r.tools_used):<3} "
            f"task_tracker={tt_count}"
        )
        if r.keyword_misses:
            print(f"       Missing keywords: {r.keyword_misses}")
        if r.error:
            print(f"       Error: {r.error[:100]}")

    total_tt = sum(len(r.task_tracker_events) for r in results)
    print(f"\nTotal task_tracker events: {total_tt}")
    print(f"Total time: {sum(r.duration_s for r in results):.1f}s")

    if total_tt == 0:
        print("\nWARNING: No task_tracker usage detected in any task!")
        print("The task_tracker tool may not be working as expected.")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
