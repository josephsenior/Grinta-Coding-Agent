"""Comprehensive manual agent test through the live server.

Exercises multiple task types and reports pass/fail for each.
Usage:
    uv run python scripts/live_manual_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from client import AppClient

BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:3000')
TASK_TIMEOUT = int(os.environ.get('APP_TASK_TIMEOUT', '180'))


@dataclass
class TaskResult:
    name: str
    passed: bool
    duration: float
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str = ''
    all_text: str = ''  # agent-produced content only (streaming + messages)
    agent_final: str = ''  # last non-streaming agent message


# ──────────────────────────────────────────────────────────────────────────────
# Task definitions
# ──────────────────────────────────────────────────────────────────────────────

TASKS: list[dict[str, Any]] = [
    # 1) Simple factual question — no tools needed
    {
        'name': 'simple_question',
        'prompt': 'What is the capital of France? Reply with just the city name, nothing else.',
        'check': lambda txt: 'paris' in txt.lower(),
        'description': 'Simple factual Q&A (no tools)',
    },
    # 2) Code generation — write a function
    {
        'name': 'code_generation',
        'prompt': (
            "Create a file called 'test_output_fibonacci.py' that contains a Python function "
            "'fibonacci(n)' which returns the nth Fibonacci number (0-indexed, so fibonacci(0)=0, "
            "fibonacci(1)=1, fibonacci(10)=55). Include a few assert statements at the bottom "
            "to verify it works."
        ),
        # "wrote" only appears in agent write-confirmation messages, not the prompt
        'check': lambda txt: 'wrote' in txt.lower() or 'fibonacci' in txt.lower(),
        'description': 'Code generation (create file with function)',
    },
    # 3) File reading / analysis — must read the file to know the Python version
    {
        'name': 'code_analysis',
        'prompt': (
            "Read the file 'pyproject.toml' in the project root and tell me: "
            "1) What is the project name? "
            "2) What Python version is required? "
            "3) How many optional dependency groups are there? "
            "Answer concisely."
        ),
        # Python version number only appears if the agent actually read the file
        'check': lambda txt: '3.12' in txt or '3.13' in txt,
        'description': 'Code analysis (read and summarize file)',
    },
    # 4) Shell command execution — run a command and report output
    {
        'name': 'shell_command',
        'prompt': (
            "Run the shell command 'python3 --version' and tell me what Python version is installed."
        ),
        'check': lambda txt: '3.' in txt and 'python' in txt.lower(),
        'description': 'Shell command execution',
    },
    # 5) Multi-step task — create, read, modify
    {
        'name': 'multi_step_edit',
        'prompt': (
            "1. Create a file called 'test_output_greeting.txt' with the content 'Hello World'\n"
            "2. Read the file back to confirm it was created\n"
            "3. Edit the file to say 'Hello there' instead\n"
            "4. Read it one more time and confirm the edit worked\n"
            "When finished, summarize each step you took."
        ),
        # "wrote" only appears in agent tool confirmations, not the user prompt
        'check': lambda txt: ('wrote' in txt.lower() or 'written' in txt.lower() or 'created' in txt.lower()),
        'description': 'Multi-step file create/read/edit',
    },
    # 6) Debugging — find an issue in code
    {
        'name': 'debug_analysis',
        'prompt': (
            "Here is a Python function with a bug:\n\n"
            "```python\n"
            "def average(numbers):\n"
            "    total = 0\n"
            "    for n in numbers:\n"
            "        total += n\n"
            "    return total / len(numbers)\n"
            "```\n\n"
            "What happens if you call average([])? What's the bug and how would you fix it?"
        ),
        'check': lambda txt: (
            'zero' in txt.lower() or 'empty' in txt.lower() or 'division' in txt.lower()
        ),
        'description': 'Bug analysis (identify division by zero)',
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _agent_state(event: dict) -> str:
    extras = event.get('extras') or {}
    if isinstance(extras, dict):
        state = extras.get('agent_state')
        if isinstance(state, str):
            return state.upper()
    return ''


# ──────────────────────────────────────────────────────────────────────────────
# Per-task runner
# ──────────────────────────────────────────────────────────────────────────────


async def run_task(client: AppClient, task: dict[str, Any]) -> TaskResult:
    """Run a single task through the live server and return results."""
    name = task['name']
    prompt = task['prompt']
    check_fn = task['check']
    events: list[dict[str, Any]] = []
    # Only collect content the AGENT produces after the prompt is sent — this
    # prevents check functions from false-positiving on words in the prompt.
    agent_content_parts: list[str] = []
    terminal = asyncio.Event()
    error_msg = ''
    prompt_sent = False
    # Track whether the agent has been in RUNNING state (after the user message
    # was processed), so we can distinguish the startup AWAITING_USER_INPUT from
    # the post-response AWAITING_USER_INPUT.
    has_been_running = False

    async def on_event(event: dict) -> None:
        nonlocal prompt_sent, has_been_running
        events.append(event)
        state = _agent_state(event)
        action = event.get('action', '')
        source = event.get('source', '')
        msg = event.get('message') or ''
        args = event.get('args') or {}
        eid = event.get('id', '')

        head = state or event.get('observation', '') or action or event.get('type', '?')
        print(f'    [{name}] {head} id={eid} {str(msg)[:100]}')

        if state == 'RUNNING':
            has_been_running = True

        # Collect agent-produced content only (never user text or system prompts)
        if prompt_sent and source not in ('user',):
            if action == 'streaming_chunk' and isinstance(args, dict):
                # Use the incremental "chunk" for token-by-token accumulation.
                # On the final chunk (is_final=True), "accumulated" contains the
                # complete LLM response — use that if available to avoid gaps.
                if args.get('is_final') and args.get('accumulated'):
                    # Replace all previously collected streaming chunks with the
                    # full accumulated text.
                    agent_content_parts[:] = [p for p in agent_content_parts
                                              if not getattr(p, '_is_chunk', False)]
                    agent_content_parts.append(args['accumulated'])
                else:
                    tok = args.get('chunk', '')
                    if tok:
                        agent_content_parts.append(tok)
            elif isinstance(msg, str) and msg.strip() and action not in ('system',):
                agent_content_parts.append(msg)

        # Terminal detection — rely on authoritative server-side state.
        # AWAITING_USER_INPUT after RUNNING means the agent finished its turn
        # and returned control to the user (covers Q&A tasks that don't call
        # finish explicitly).  The startup AWAITING_USER_INPUT fires BEFORE
        # RUNNING and has_been_running will be False at that point.
        if state in {'FINISHED', 'STOPPED', 'ERROR', 'REJECTED'}:
            terminal.set()
        elif action == 'finish':
            terminal.set()
        elif state == 'AWAITING_USER_INPUT' and has_been_running and prompt_sent:
            terminal.set()

    start = time.monotonic()
    try:
        print(f"  Creating conversation for '{name}'...")
        conv = await asyncio.wait_for(client.create_conversation(), timeout=120)
        conv_id = conv.get('id') or conv.get('conversation_id')
        if not conv_id:
            return TaskResult(
                name=name, passed=False, duration=0, error='No conversation ID'
            )
        print(f'  Conversation: {conv_id}')

        await asyncio.wait_for(client.start_agent(str(conv_id)), timeout=120)

        await client.join_conversation(
            conversation_id=str(conv_id), on_event=on_event
        )

        # Wait for the agent to signal it is ready for input
        print('  Waiting for AWAITING_USER_INPUT...')
        ready_deadline = time.monotonic() + 30.0
        while not any(_agent_state(e) == 'AWAITING_USER_INPUT' for e in events):
            await asyncio.sleep(0.3)
            if time.monotonic() > ready_deadline:
                error_msg = 'Timed out waiting for AWAITING_USER_INPUT'
                break

        if not error_msg:
            print('  Sending prompt...')
            await client.send_message(prompt)
            prompt_sent = True

            try:
                await asyncio.wait_for(terminal.wait(), timeout=TASK_TIMEOUT)
            except TimeoutError:
                error_msg = f'Timed out after {TASK_TIMEOUT}s (agent never reached FINISHED/STOPPED)'

        await client.leave_conversation()
        await asyncio.sleep(0.3)

    except Exception as exc:
        import traceback
        error_msg = f'{type(exc).__name__}: {exc}\n{traceback.format_exc()[:400]}'

    elapsed = time.monotonic() - start
    all_text = '\n'.join(agent_content_parts)

    # Last non-streaming agent message
    agent_final = ''
    for e in reversed(events):
        if e.get('action') not in ('streaming_chunk', 'system') and e.get('source') == 'agent' and e.get('message'):
            agent_final = str(e['message'])[:300]
            break

    passed = check_fn(all_text) if not error_msg else False

    return TaskResult(
        name=name,
        passed=passed,
        duration=elapsed,
        events=events,
        error=error_msg,
        all_text=all_text,
        agent_final=agent_final,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Server health & restart
# ──────────────────────────────────────────────────────────────────────────────

async def _ensure_server_healthy(client: AppClient) -> bool:
    """Check server health; restart if unreachable. Returns True if healthy."""
    import subprocess

    import httpx as _httpx

    for attempt in range(2):  # first try + one restart
        try:
            async with _httpx.AsyncClient(timeout=5) as hc:
                resp = await hc.get(f'{BASE_URL}/api/health/ready')
                if resp.status_code == 200:
                    return True
        except Exception:
            pass

        if attempt == 0:
            print('  Server unhealthy — attempting restart...')
            # Kill existing server processes
            try:
                subprocess.run(  # noqa: ASYNC221
                    ['powershell', '-Command',
                     "Get-Process python -ErrorAction SilentlyContinue | "
                     "Where-Object { (Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.Id)\").CommandLine -match 'start_server' } | "
                     "Stop-Process -Force"],
                    timeout=10, capture_output=True,
                )
            except Exception:
                pass
            await asyncio.sleep(2)
            # Start new server
            project_root = os.path.join(os.path.dirname(__file__), '..')
            subprocess.Popen(  # noqa: ASYNC220
                ['uv', 'run', 'python', 'start_server.py'],
                cwd=project_root,
                stdout=open(os.path.join(project_root, 'server_live_test.log'), 'w'),  # noqa: ASYNC230
                stderr=open(os.path.join(project_root, 'server_live_test_err.log'), 'w'),  # noqa: ASYNC230
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
            # Wait for server to come up
            for _ in range(30):
                await asyncio.sleep(1)
                try:
                    async with _httpx.AsyncClient(timeout=3) as hc:
                        resp = await hc.get(f'{BASE_URL}/api/health/ready')
                        if resp.status_code == 200:
                            print('  Server restarted successfully')
                            return True
                except Exception:
                    continue
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


async def main() -> int:
    print(f"{'=' * 72}")
    print('  GRINTA LIVE AGENT MANUAL TEST')
    print(f'  Server: {BASE_URL}')
    print(f'  Task timeout: {TASK_TIMEOUT}s')
    print(f"{'=' * 72}\n")

    client = AppClient(BASE_URL)

    print('Checking server health...')
    try:
        import httpx as _httpx

        async with _httpx.AsyncClient(timeout=10) as hc:
            resp = await hc.get(f'{BASE_URL}/api/health/ready')
            data = resp.json()
            status = data.get('status', '?')
            print(f'  Status: {status}\n')
            if status != 'ready':
                print(f'  WARNING: {data}')
    except Exception as exc:
        print(f'  FAILED: server not reachable — {exc}')
        print('  Start the server: uv run python start_server.py')
        return 1

    results: list[TaskResult] = []

    for i, task in enumerate(TASKS, 1):
        print(f"\n{'─' * 72}")
        print(f"  TASK {i}/{len(TASKS)}: {task['description']}")
        print(f"{'─' * 72}")

        # On Windows, the IOCP ProactorEventLoop can crash the server's accept
        # loop after a WebSocket disconnects.  Detect and auto-restart.
        if not await _ensure_server_healthy(client):
            print('  Server unreachable — cannot run task')
            results.append(TaskResult(
                name=task['name'], passed=False, duration=0,
                error='Server crashed and could not be restarted',
            ))
            continue

        result = await run_task(client, task)
        results.append(result)

        status_str = 'PASS ✓' if result.passed else 'FAIL ✗'
        print(f'\n  Result: {status_str} ({result.duration:.1f}s)')
        if result.error:
            print(f'  Error: {result.error[:300]}')
        if result.agent_final:
            print(f'  Agent final: {result.agent_final}')
        if not result.passed and result.all_text:
            print(f'  Agent output: {result.all_text[:300]}')

    print(f"\n{'=' * 72}")
    print('  SUMMARY')
    print(f"{'=' * 72}")
    total = len(results)
    passed = sum(1 for r in results if r.passed)

    for r in results:
        s = 'PASS' if r.passed else 'FAIL'
        err = f' ({r.error[:60]})' if r.error else ''
        print(f'  {s:4}  {r.duration:6.1f}s  {r.name}{err}')

    total_time = sum(r.duration for r in results)
    print(f'\n  {passed}/{total} passed in {total_time:.1f}s')
    print(f"{'=' * 72}")

    out = os.path.join(os.path.dirname(__file__), '..', 'live_test_results.json')
    with open(out, 'w') as f:  # noqa: ASYNC230
        json.dump(
            [
                {
                    'name': r.name,
                    'passed': r.passed,
                    'duration': round(r.duration, 2),
                    'error': r.error,
                    'event_count': len(r.events),
                    'agent_final': r.agent_final,
                    'all_text': r.all_text[:500],
                }
                for r in results
            ],
            f,
            indent=2,
        )
    print('\n  Results saved to live_test_results.json')
    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
