"""Headless SWE tests — validates agent runtime behavior on real tasks.

Run:  python scripts/headless_swe_tests.py
Env:
  FORGE_BASE_URL  (default: http://localhost:3000)
  FORGE_TIMEOUT   (default: 600)  seconds to wait for agent
"""

import asyncio
import json
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from forge_client import ForgeClient

BASE_URL = os.environ.get("FORGE_BASE_URL", "http://localhost:3000")
TIMEOUT = int(os.environ.get("FORGE_TIMEOUT", "600"))

# ---------------------------------------------------------------------------
# Test scenarios: simple → complex
# ---------------------------------------------------------------------------
SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "simple_file_create",
        "prompt": (
            "Create a file called 'hello.txt' in the workspace with the content:\n"
            "Hello from Forge!\n"
            "Then confirm it was created by reading it back."
        ),
        "check": lambda events: any(
            "hello.txt" in str(e.get("message", "")) or
            e.get("action") == "finish" or
            e.get("observation") == "agent_finish"
            for e in events
        ),
        "description": "Basic file creation + read-back",
    },
    {
        "name": "python_script_write_and_run",
        "prompt": (
            "Create a Python script called 'fizzbuzz.py' that prints FizzBuzz for numbers 1-20.\n"
            "Then run the script and show me the output."
        ),
        "check": lambda events: any(
            "Fizz" in str(e.get("message", "")) or
            "fizzbuzz" in str(e.get("message", "")).lower()
            for e in events
        ),
        "description": "Write Python code, execute it, verify output",
    },
    {
        "name": "bug_fix_task",
        "prompt": (
            "Create a file 'calculator.py' with this buggy code:\n\n"
            "```python\n"
            "def add(a, b):\n"
            "    return a - b  # BUG: should be +\n\n"
            "def multiply(a, b):\n"
            "    return a * b\n\n"
            "if __name__ == '__main__':\n"
            "    print(f'2 + 3 = {add(2, 3)}')\n"
            "    print(f'4 * 5 = {multiply(4, 5)}')\n"
            "```\n\n"
            "Then fix the bug in the add function and run the script to verify the fix."
        ),
        "check": lambda events: any(
            "2 + 3 = 5" in str(e.get("message", ""))
            for e in events
        ),
        "description": "Create buggy code, diagnose, fix, verify",
    },
    {
        "name": "multi_file_project",
        "prompt": (
            "Create a small project with these files:\n"
            "1. 'utils.py' with a function `greet(name)` that returns f'Hello, {name}!'\n"
            "2. 'test_utils.py' with a simple test that calls greet('World') and asserts the result\n"
            "3. Run the test file and confirm it passes"
        ),
        "check": lambda events: any(
            e.get("action") == "finish" or e.get("observation") == "agent_finish"
            for e in events
        ),
        "description": "Multi-file project with tests",
    },
    {
        "name": "git_and_checkpoint",
        "prompt": (
            "Initialize a git repository in the workspace.\n"
            "Create a file 'README.md' with content '# My Project\\nVersion 1.0'.\n"
            "Stage and commit it with message 'Initial commit'.\n"
            "Then list the git log to confirm the commit."
        ),
        "check": lambda events: any(
            "Initial commit" in str(e.get("message", "")) or
            "commit" in str(e.get("message", "")).lower()
            for e in events
        ),
        "description": "Git init, add, commit, log",
    },
]


class TestResult:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.status = "NOT_RUN"
        self.duration = 0.0
        self.events: list[dict] = []
        self.error: str | None = None
        self.terminal_state: str | None = None
        self.tool_calls: list[str] = []
        self.issues: list[str] = []

    def summary_line(self) -> str:
        icon = {"PASS": "OK", "FAIL": "FAIL", "TIMEOUT": "TIME", "ERROR": "ERR"}.get(
            self.status, "????"
        )
        return (
            f"  {icon:4s}  {self.name:<30s}  {self.duration:6.1f}s  "
            f"steps={len(self.tool_calls):<3d}  {self.description}"
        )


async def run_scenario(scenario: dict[str, Any]) -> TestResult:
    result = TestResult(scenario["name"], scenario["description"])
    t0 = time.time()

    events: list[dict] = []
    terminal = asyncio.Event()
    last_state: str | None = None
    saw_finish = False

    def _agent_state(event: dict) -> str:
        extras = event.get("extras") or {}
        if isinstance(extras, dict):
            s = extras.get("agent_state")
            if isinstance(s, str) and s:
                return s.upper()
        return ""

    async def on_event(event: dict) -> None:
        nonlocal last_state, saw_finish
        events.append(event)

        state = _agent_state(event)
        if state:
            last_state = state

        action = event.get("action", "")
        observation = event.get("observation", "")

        # Track tool calls (non-streaming, non-think actions)
        if action and action not in ("streaming_chunk", "finish", ""):
            if action != "think":
                result.tool_calls.append(action)

        if action == "finish" or observation == "agent_finish":
            saw_finish = True

        if state in ("FINISHED", "STOPPED", "ERROR", "REJECTED"):
            terminal.set()
        if action == "finish" or observation == "agent_finish":
            terminal.set()

    client = ForgeClient(BASE_URL)
    try:
        conv = await asyncio.wait_for(client.create_conversation(), timeout=30)
        conv_id = conv.get("id") or conv.get("conversation_id")
        if not conv_id:
            result.status = "ERROR"
            result.error = f"No conversation ID in response: {conv}"
            return result

        await asyncio.wait_for(client.start_agent(str(conv_id)), timeout=30)
        await client.join_conversation(conversation_id=str(conv_id), on_event=on_event)
        await asyncio.sleep(0.5)

        # Wait for AWAITING_USER_INPUT
        init_deadline = time.time() + 60
        while last_state != "AWAITING_USER_INPUT" and time.time() < init_deadline:
            await asyncio.sleep(0.5)

        await client.send_message(scenario["prompt"])

        try:
            await asyncio.wait_for(terminal.wait(), timeout=TIMEOUT)
        except TimeoutError:
            result.status = "TIMEOUT"
            result.error = f"Agent did not reach terminal state within {TIMEOUT}s"
            result.issues.append("timeout_no_terminal_state")

        result.terminal_state = last_state
        result.events = events
        result.duration = time.time() - t0

        # Evaluate
        if result.status != "TIMEOUT":
            if last_state in ("ERROR", "REJECTED"):
                result.status = "FAIL"
                result.error = f"Terminal state: {last_state}"
            elif saw_finish or last_state in ("FINISHED", "STOPPED"):
                check_fn = scenario.get("check")
                if check_fn and not check_fn(events):
                    result.status = "FAIL"
                    result.error = "Check function returned False"
                    result.issues.append("check_failed")
                else:
                    result.status = "PASS"
            else:
                result.status = "FAIL"
                result.error = f"Unexpected terminal state: {last_state}"

        # Detect runtime issues
        _detect_issues(result, events)

    except Exception as exc:
        result.status = "ERROR"
        result.error = str(exc)
        result.duration = time.time() - t0
    finally:
        try:
            await client.leave_conversation()
        except Exception:
            pass
        await client.close()

    return result


def _detect_issues(result: TestResult, events: list[dict]) -> None:
    """Scan events for common runtime/agentic issues."""

    # 1. Repeated identical tool calls (stuck in loop)
    if len(result.tool_calls) > 3:
        for i in range(len(result.tool_calls) - 2):
            if (
                result.tool_calls[i] == result.tool_calls[i + 1] == result.tool_calls[i + 2]
            ):
                result.issues.append(f"repeated_tool_call:{result.tool_calls[i]}")
                break

    # 2. Error events
    error_events = [
        e for e in events
        if _agent_state_from(e) == "ERROR" or e.get("action") == "error"
    ]
    if error_events:
        result.issues.append(f"error_events:{len(error_events)}")

    # 3. Excessive streaming chunks with no tool calls
    stream_chunks = sum(1 for e in events if e.get("action") == "streaming_chunk")
    if stream_chunks > 50 and len(result.tool_calls) == 0:
        result.issues.append(f"streaming_only_no_tools:chunks={stream_chunks}")

    # 4. Very high step count (inefficient)
    if len(result.tool_calls) > 20:
        result.issues.append(f"high_step_count:{len(result.tool_calls)}")

    # 5. Context limit errors
    context_errors = [
        e for e in events
        if "context" in str(e.get("message", "")).lower()
        and "limit" in str(e.get("message", "")).lower()
    ]
    if context_errors:
        result.issues.append("context_limit_hit")


def _agent_state_from(event: dict) -> str:
    extras = event.get("extras") or {}
    if isinstance(extras, dict):
        s = extras.get("agent_state")
        if isinstance(s, str):
            return s.upper()
    return ""


async def main() -> int:
    print(f"Forge Headless SWE Tests")
    print(f"Server: {BASE_URL}  |  Timeout: {TIMEOUT}s per scenario")
    print("=" * 78)

    # Verify server is up
    import httpx
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{BASE_URL}/api/health/live", timeout=5)
            health = resp.json()
            print(f"Server health: {health}")
    except Exception as exc:
        print(f"Server not reachable: {exc}")
        return 1

    # Pick scenarios to run
    scenario_filter = os.environ.get("FORGE_TEST_SCENARIO", "").strip()
    if scenario_filter:
        scenarios = [s for s in SCENARIOS if s["name"] == scenario_filter]
        if not scenarios:
            print(f"Unknown scenario: {scenario_filter}")
            print(f"Available: {', '.join(s['name'] for s in SCENARIOS)}")
            return 1
    else:
        scenarios = SCENARIOS

    results: list[TestResult] = []

    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{'─' * 78}")
        print(f"[{i}/{len(scenarios)}] {scenario['name']}: {scenario['description']}")
        print(f"{'─' * 78}")
        t = time.time()
        result = await run_scenario(scenario)
        print(f"  → {result.status} ({result.duration:.1f}s, {len(result.tool_calls)} tool calls)")
        if result.error:
            print(f"  → Error: {result.error}")
        if result.issues:
            print(f"  → Issues: {', '.join(result.issues)}")
        results.append(result)

    # Summary
    print(f"\n{'=' * 78}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 78}")
    for r in results:
        print(r.summary_line())
    print(f"{'─' * 78}")

    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    errors = sum(1 for r in results if r.status == "ERROR")
    timeouts = sum(1 for r in results if r.status == "TIMEOUT")
    print(f"Total: {len(results)}  Pass: {passed}  Fail: {failed}  Error: {errors}  Timeout: {timeouts}")

    # Aggregate issues
    all_issues = []
    for r in results:
        for issue in r.issues:
            all_issues.append(f"{r.name}: {issue}")
    if all_issues:
        print(f"\nDETECTED ISSUES:")
        for issue in all_issues:
            print(f"  - {issue}")

    return 0 if failed == 0 and errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
