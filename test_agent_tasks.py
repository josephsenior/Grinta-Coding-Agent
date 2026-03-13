#!/usr/bin/env python3
"""
Test the Forge agent on non-file-editing tasks:
  - Simple Q&A
  - Research / analysis
  - Planning
  - Debugging

Usage:
    1. Start the server:  $env:FORGE_WATCH="0"; python start_server.py
    2. Run this script:   python test_agent_tasks.py
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

BASE = os.environ.get("FORGE_BASE_URL", "http://127.0.0.1:3000")
POLL_INTERVAL = 3          # seconds between polls
READY_TIMEOUT = 120        # max seconds to wait for runtime ready
TASK_TIMEOUT = 300         # max seconds per task

# ── Task definitions ────────────────────────────────────────────────────────

TASKS: list[dict] = [
    # 1 ─ Simple factual Q&A (no tools needed, pure LLM)
    {
        "name": "Simple Q&A",
        "category": "question",
        "prompt": (
            "What are the main differences between Python lists and tuples? "
            "Give a short, clear answer with examples."
        ),
        "expect_tools": False,
        "success_keywords": ["immutable", "mutable", "tuple", "list"],
    },

    # 2 ─ Research / code analysis (uses browse/read tools)
    {
        "name": "Codebase research",
        "category": "research",
        "prompt": (
            "Examine this project's codebase and tell me: "
            "1) What programming languages are used? "
            "2) What is the high-level architecture (backend, frontend, CLI)? "
            "3) What LLM provider is configured? "
            "Answer concisely."
        ),
        "expect_tools": True,
        "success_keywords": ["python", "backend", "frontend"],
    },

    # 3 ─ Planning (structured thinking, no tools strictly needed)
    {
        "name": "Project planning",
        "category": "planning",
        "prompt": (
            "I want to add a REST API rate limiter to this project's backend. "
            "Create a detailed plan with: "
            "1) Which files need to be modified "
            "2) What library/approach to use "
            "3) Step-by-step implementation order "
            "Do NOT implement anything — just give me the plan."
        ),
        "expect_tools": True,
        "success_keywords": ["rate limit", "middleware", "step"],
    },

    # 4 ─ Debugging (analysis + tool use)
    {
        "name": "Debug analysis",
        "category": "debugging",
        "prompt": (
            "I'm getting this Python error in my project:\n\n"
            "```\n"
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 42, in handle_request\n"
            "    data = json.loads(request.body)\n"
            "  File \"/usr/lib/python3.12/json/__init__.py\", line 346, in loads\n"
            "    return _default_decoder.decode(s)\n"
            "json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)\n"
            "```\n\n"
            "What's causing this error? What are the common fixes? "
            "Give me a clear explanation and solution."
        ),
        "expect_tools": False,
        "success_keywords": ["empty", "body", "json", "decode"],
    },

    # 5 ─ Math / reasoning
    {
        "name": "Logical reasoning",
        "category": "question",
        "prompt": (
            "A farmer has 17 sheep. All but 9 die. How many sheep does the farmer have left? "
            "Explain your reasoning step by step."
        ),
        "expect_tools": False,
        "success_keywords": ["9"],
    },
]

# ── Helpers ──────────────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    name: str
    category: str
    status: str = "not_run"        # passed / failed / timeout / error
    agent_state: str = ""
    duration_s: float = 0.0
    events: list = field(default_factory=list)
    answer_text: str = ""
    tools_used: list = field(default_factory=list)
    keyword_hits: list = field(default_factory=list)
    keyword_misses: list = field(default_factory=list)
    error: str = ""


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
    """Poll until agent_state is in target_states or timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        resp = api("GET", f"/api/v1/conversations/{cid}")
        state = resp.get("agent_state", "unknown")
        if state in target_states:
            return state
        time.sleep(POLL_INTERVAL)
    return "timeout"


def collect_events(cid: str) -> list[dict]:
    """Fetch all events from the conversation."""
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


def extract_answer_and_tools(events: list[dict]) -> tuple[str, list[str]]:
    """Pull the agent's text answer and list of tool actions from events."""
    answer_parts = []
    tools = []
    for ev in events:
        action = ev.get("action", "")
        obs = ev.get("observation", "")
        args = ev.get("args", {})

        # Agent messages / thoughts
        if action == "message" and ev.get("source") == "agent":
            content = args.get("content", "") or ev.get("message", "")
            if content:
                answer_parts.append(content)
        elif action == "think":
            content = args.get("content", "")
            if content:
                answer_parts.append(f"[think] {content}")

        # Finish action (agent's final answer)
        if action == "finish":
            content = args.get("outputs", {}).get("content", "") or args.get("content", "")
            thought = args.get("thought", "")
            if content:
                answer_parts.append(content)
            if thought:
                answer_parts.append(f"[finish-thought] {thought}")

        # Write action content (agent may write answer to file)
        if action == "write":
            file_text = args.get("file_text", "") or args.get("content", "")
            if file_text:
                answer_parts.append(file_text)

        # Tool usage
        if action in ("run", "read", "browse", "write", "edit"):
            cmd = args.get("command", "") or args.get("path", "")
            tools.append(f"{action}: {cmd[:80]}")

        # Observations with content
        if obs and ev.get("source") == "agent":
            answer_parts.append(obs)

    return "\n".join(answer_parts), tools


def check_keywords(text: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    lower = text.lower()
    hits = [k for k in keywords if k.lower() in lower]
    misses = [k for k in keywords if k.lower() not in lower]
    return hits, misses


# ── Main ─────────────────────────────────────────────────────────────────────

def run_task(task: dict) -> TaskResult:
    result = TaskResult(name=task["name"], category=task["category"])
    print(f"\n{'='*60}")
    print(f"TASK: {task['name']}  [{task['category']}]")
    print(f"{'='*60}")
    print(f"Prompt: {task['prompt'][:120]}...")

    # 1. Create conversation
    resp = api("POST", "/api/v1/conversations", {})
    cid = resp.get("conversation_id")
    if not cid:
        result.status = "error"
        result.error = f"Failed to create conversation: {resp}"
        print(f"  ERROR: {result.error}")
        return result
    print(f"  Conversation: {cid}")

    # 2. Wait for runtime ready
    print(f"  Waiting for runtime ready (up to {READY_TIMEOUT}s)...")
    state = wait_for_state(cid, {"awaiting_user_input"}, READY_TIMEOUT)
    if state == "timeout":
        result.status = "timeout"
        result.error = "Runtime did not become ready"
        print(f"  TIMEOUT waiting for ready state")
        return result
    print(f"  Runtime ready!")

    # 3. Send task
    t0 = time.time()
    resp = api("POST", f"/api/v1/conversations/{cid}/events/raw",
               body=task["prompt"], ct="text/plain")
    if "error" in resp:
        result.status = "error"
        result.error = f"Send failed: {resp}"
        print(f"  ERROR sending task: {resp}")
        return result
    print(f"  Task sent. Polling...")

    # 4. Poll for completion
    final_state = wait_for_state(
        cid,
        {"awaiting_user_input", "finished", "stopped", "error"},
        TASK_TIMEOUT,
    )
    result.duration_s = time.time() - t0
    result.agent_state = final_state

    if final_state == "timeout":
        result.status = "timeout"
        result.error = f"Agent did not finish within {TASK_TIMEOUT}s"
        print(f"  TIMEOUT after {result.duration_s:.1f}s")
    elif final_state == "error":
        result.status = "error"
        result.error = "Agent ended in error state"
        print(f"  ERROR state after {result.duration_s:.1f}s")
    else:
        print(f"  Completed in {result.duration_s:.1f}s (state={final_state})")

    # 5. Collect events
    result.events = collect_events(cid)
    result.answer_text, result.tools_used = extract_answer_and_tools(result.events)

    # 6. Keyword check
    combined_text = result.answer_text
    for ev in result.events:
        # Also check observation text and args content
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
    for t in result.tools_used[:5]:
        print(f"    - {t}")
    if len(result.tools_used) > 5:
        print(f"    ... and {len(result.tools_used)-5} more")
    print(f"  Keywords hit: {result.keyword_hits}")
    if result.keyword_misses:
        print(f"  Keywords MISSED: {result.keyword_misses}")

    # Print first 500 chars of answer
    if result.answer_text:
        preview = result.answer_text[:500]
        print(f"\n  --- Answer preview ---")
        for line in preview.split("\n"):
            print(f"  | {line}")
        if len(result.answer_text) > 500:
            print(f"  | ... ({len(result.answer_text)} chars total)")

    return result


def main():
    # Check server is reachable
    print(f"Checking server at {BASE}...")
    try:
        resp = api("GET", "/api/v1/conversations")
        if isinstance(resp.get("error"), int) and resp["error"] >= 500:
            print(f"Server error: {resp}")
            print(f"Start it with:  $env:FORGE_WATCH='0'; python start_server.py")
            sys.exit(1)
    except Exception as e:
        print(f"Server not reachable: {e}")
        print(f"Start it with:  $env:FORGE_WATCH='0'; python start_server.py")
        sys.exit(1)
    print("Server is up!\n")

    # Run tasks sequentially
    results: list[TaskResult] = []
    for task in TASKS:
        try:
            r = run_task(task)
            results.append(r)
        except Exception as e:
            r = TaskResult(name=task["name"], category=task["category"],
                           status="error", error=str(e))
            results.append(r)
            print(f"  EXCEPTION: {e}")

    # ── Final report ─────────────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print(f"FINAL REPORT")
    print(f"{'='*60}")
    
    passed = sum(1 for r in results if r.status == "passed")
    partial = sum(1 for r in results if r.status == "partial")
    failed = sum(1 for r in results if r.status in ("failed", "error", "timeout"))
    total = len(results)

    print(f"\nResults: {passed}/{total} passed, {partial} partial, {failed} failed\n")
    
    for r in results:
        icon = {"passed": "OK", "partial": "~~", "timeout": "TO", "error": "!!", "failed": "XX"}.get(r.status, "??")
        print(f"  [{icon}] {r.name:<25} {r.category:<12} {r.duration_s:6.1f}s  "
              f"events={len(r.events):<4} tools={len(r.tools_used)}")
        if r.keyword_misses:
            print(f"       Missing keywords: {r.keyword_misses}")
        if r.error:
            print(f"       Error: {r.error[:100]}")

    print(f"\nTotal time: {sum(r.duration_s for r in results):.1f}s")

    # Return exit code
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
