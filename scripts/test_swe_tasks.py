"""Headless SWE task tests against the local App server.

Each task creates a concrete coding problem and verifies the agent solves it.
"""

import asyncio
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from client import AppClient

BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:3000')
WAIT_SECONDS = int(os.environ.get('APP_WAIT_SECONDS', '300'))


# Match the project_root configured in settings.json.
# Override with APP_WORKSPACE env var if needed.
def _get_workspace() -> str:
    env = os.environ.get('APP_WORKSPACE', '').strip()
    if env:
        return os.path.abspath(env)
    # Try to read from settings.json next to this file
    settings_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'settings.json'
    )
    try:
        import json

        with open(settings_path, encoding='utf-8') as f:
            s = json.load(f)
        pr = (s.get('project_root') or '').strip()
        if pr:
            return os.path.abspath(pr)
    except Exception:
        pass
    # Fallback: App repo root (works when project_root is empty = cwd)
    return os.path.abspath(os.path.dirname(__file__))


WORKSPACE = _get_workspace()


TASKS = [
    {
        'name': 'bug_fix',
        'description': 'Fix an off-by-one bug in a Python function',
        'setup_files': {
            'swe_task_bugfix.py': (
                'def sum_of_squares(n):\n'
                '    """Return 1^2 + 2^2 + ... + n^2."""\n'
                '    total = 0\n'
                '    for i in range(1, n):  # BUG: off-by-one, should be range(1, n + 1)\n'
                '        total += i * i\n'
                '    return total\n'
            ),
        },
        'output_files': ['swe_task_bugfix.py'],
        'prompt': (
            'There is a bug in the file `swe_task_bugfix.py` in the current directory.\n'
            'The function `sum_of_squares(n)` should return 1^2 + 2^2 + ... + n^2.\n'
            'For example: sum_of_squares(3) should return 14 (=1+4+9), but currently returns 5 (=1+4, misses 9).\n\n'
            'The bug is an off-by-one error: it uses `range(1, n)` but should use `range(1, n + 1)`.\n'
            'Fix the bug in the file and verify the function works correctly by running it.'
        ),
        'verify': lambda files: (
            'range(1, n + 1)' in files.get('swe_task_bugfix.py', '')
            or 'range(1, n+1)' in files.get('swe_task_bugfix.py', '')
        ),
    },
    {
        'name': 'feature_add',
        'description': 'Add a new function to an existing Python module',
        'setup_files': {
            'swe_task_utils.py': (
                '"""Utility functions."""\n\n'
                'def add(a, b):\n'
                '    """Return a + b."""\n'
                '    return a + b\n\n'
                'def subtract(a, b):\n'
                '    """Return a - b."""\n'
                '    return a - b\n'
            ),
        },
        'output_files': ['swe_task_utils.py'],
        'prompt': (
            'Open `swe_task_utils.py` in the current directory.\n'
            'Add a new function `multiply(a, b)` that returns a * b, following the same style as the existing functions.\n'
            'Also add a `divide(a, b)` function that returns a / b and raises ValueError if b is 0.\n'
            'Keep the existing functions unchanged.'
        ),
        'verify': lambda files: (
            'def multiply' in files.get('swe_task_utils.py', '')
            and 'def divide' in files.get('swe_task_utils.py', '')
            and 'def add' in files.get('swe_task_utils.py', '')
        ),
    },
    {
        'name': 'write_tests',
        'description': 'Write unit tests for an existing module',
        'setup_files': {
            'swe_task_calc.py': (
                'def factorial(n):\n'
                '    """Return n! for non-negative integers."""\n'
                '    if n < 0:\n'
                "        raise ValueError('n must be non-negative')\n"
                '    if n == 0:\n'
                '        return 1\n'
                '    return n * factorial(n - 1)\n\n'
                'def is_prime(n):\n'
                '    """Return True if n is a prime number."""\n'
                '    if n < 2:\n'
                '        return False\n'
                '    for i in range(2, int(n**0.5) + 1):\n'
                '        if n % i == 0:\n'
                '            return False\n'
                '    return True\n'
            ),
        },
        'output_files': ['swe_task_tests.py'],
        'prompt': (
            'Write unit tests for the functions in `swe_task_calc.py` (in the current directory).\n'
            "Create a new file `swe_task_tests.py` using Python's `unittest` module.\n"
            'Requirements:\n'
            '- Test `factorial`: normal cases (0, 1, 5), negative input raises ValueError\n'
            '- Test `is_prime`: primes (2, 3, 7, 11), non-primes (0, 1, 4, 9)\n'
            '- Use descriptive test method names\n'
            'After writing, run the tests to confirm they pass.'
        ),
        'verify': lambda files: (
            'import unittest' in files.get('swe_task_tests.py', '')
            and 'factorial' in files.get('swe_task_tests.py', '')
            and 'is_prime' in files.get('swe_task_tests.py', '')
        ),
    },
    {
        'name': 'refactor_and_document',
        'description': 'Refactor duplicated code and add docstrings',
        'setup_files': {
            'swe_task_refactor.py': (
                'def celsius_to_fahrenheit(c):\n'
                '    return c * 9 / 5 + 32\n\n'
                'def fahrenheit_to_celsius(f):\n'
                '    return (f - 32) * 5 / 9\n\n'
                'def celsius_to_kelvin(c):\n'
                '    return c + 273.15\n\n'
                'def kelvin_to_celsius(k):\n'
                '    return k - 273.15\n\n'
                'def fahrenheit_to_kelvin(f):\n'
                '    c = (f - 32) * 5 / 9\n'
                '    return c + 273.15\n\n'
                'def kelvin_to_fahrenheit(k):\n'
                '    c = k - 273.15\n'
                '    return c * 9 / 5 + 32\n'
            ),
        },
        'output_files': ['swe_task_refactor.py'],
        'prompt': (
            'In `swe_task_refactor.py` (in the current directory), there are temperature conversion functions.\n'
            'Tasks:\n'
            '1. Add a proper docstring to each function explaining what it does, the parameter, and the return value.\n'
            '2. Notice that `fahrenheit_to_kelvin` and `kelvin_to_fahrenheit` repeat conversion logic. '
            'Refactor them to reuse `celsius_to_kelvin`, `kelvin_to_celsius`, `celsius_to_fahrenheit`, '
            'and `fahrenheit_to_celsius` instead of duplicating the math.\n'
            '3. Keep all 6 functions and make sure they still work correctly.'
        ),
        'verify': lambda files: (
            '"""' in files.get('swe_task_refactor.py', '')
            and 'def celsius_to_fahrenheit' in files.get('swe_task_refactor.py', '')
        ),
    },
]


async def run_task(task: dict, client: AppClient) -> dict:
    name = task['name']
    print(f'\n{"=" * 70}')
    print(f'TASK: {name} - {task["description"]}')
    print(f'{"=" * 70}')

    # Recreate workspace if it was removed between runs.
    os.makedirs(WORKSPACE, exist_ok=True)

    # Write setup files into workspace
    for fname, content in task.get('setup_files', {}).items():
        fpath = os.path.join(WORKSPACE, fname)
        with open(fpath, 'w', encoding='utf-8') as f:  # noqa: ASYNC230
            f.write(content)
        print(f'  Created setup file: {fname}')

    # Clean up any previous output files
    for fname in task['output_files']:
        fpath = os.path.join(WORKSPACE, fname)
        if fname not in task.get('setup_files', {}):
            if os.path.exists(fpath):
                os.remove(fpath)

    result = {
        'name': name,
        'status': 'FAIL',
        'exit_code': 1,
        'elapsed': 0.0,
        'last_state': None,
        'error': None,
    }
    start = time.time()

    try:
        print('  Creating conversation...')
        conv = await asyncio.wait_for(client.create_conversation(), timeout=120)
        conv_id = conv.get('id') or conv.get('conversation_id')
        if not conv_id:
            raise ValueError(f'No conv ID in: {conv}')
        print(f'  Conversation: {conv_id}')

        print('  Starting agent...')
        await asyncio.wait_for(client.start_agent(str(conv_id)), timeout=30)

        terminal = asyncio.Event()
        initialized = asyncio.Event()
        last_state: list[str | None] = [None]
        event_count: list[int] = [0]
        tool_calls: list[int] = [0]
        awaiting_count: list[int] = [0]

        async def on_event(event: dict) -> None:
            event_count[0] += 1
            extras = event.get('extras') or {}
            state = (
                extras.get('agent_state', '').upper()
                if isinstance(extras, dict)
                else ''
            )
            if state:
                last_state[0] = state

            action = event.get('action', '')
            obs = event.get('observation', '')

            # Print meaningful events only
            if action and action not in ('streaming_chunk',):
                msg = event.get('message') or event.get('content') or ''
                preview = str(msg).replace('\n', ' ')[:100] if msg else ''
                print(f'    [{state or action}] {preview}')
                if action not in ('message', 'recall', 'add_memory'):
                    tool_calls[0] += 1

            if state in {'AWAITING_USER_INPUT'}:
                awaiting_count[0] += 1
                if awaiting_count[0] == 1 and event.get('id') is not None:
                    initialized.set()
                elif awaiting_count[0] >= 2:
                    # Agent sent a question after receiving the task - it gave up
                    terminal.set()
            if (
                state in {'FINISHED', 'STOPPED', 'ERROR', 'REJECTED'}
                or action == 'finish'
                or obs == 'agent_finish'
            ):
                terminal.set()

        print('  Joining event stream...')
        await client.join_conversation(conversation_id=str(conv_id), on_event=on_event)
        await asyncio.sleep(0.3)

        # Wait for initialization
        try:
            await asyncio.wait_for(initialized.wait(), timeout=60)
        except TimeoutError:
            print('  Warning: init timeout, continuing...')

        print(f'  Sending prompt (task: {name})...')
        await client.send_message(task['prompt'])

        # Wait for terminal state
        try:
            await asyncio.wait_for(terminal.wait(), timeout=WAIT_SECONDS)
            print(f'  Terminal state reached: {last_state[0]}')
        except TimeoutError:
            print(
                f'  Timed out after {WAIT_SECONDS}s (state={last_state[0]}, events={event_count[0]})'
            )
            result['exit_code'] = 2
            result['status'] = 'TIMEOUT'
            result['last_state'] = last_state[0]
            result['elapsed'] = time.time() - start
            return result

        result['last_state'] = last_state[0]

        # Read output files and verify
        file_contents = {}
        for fname in task['output_files']:
            fpath = os.path.join(WORKSPACE, fname)
            if os.path.exists(fpath):
                with open(fpath, 'r', encoding='utf-8') as f:  # noqa: ASYNC230
                    file_contents[fname] = f.read()
                print(f'\n  --- {fname} ---')
                print(file_contents[fname][:800])
                if len(file_contents[fname]) > 800:
                    print(f'  ... ({len(file_contents[fname])} chars total)')
            else:
                print(f'  WARNING: output file not found: {fname}')

        if last_state[0] in {'ERROR', 'REJECTED'}:
            result['status'] = 'AGENT_ERROR'
            result['exit_code'] = 3
        elif task['verify'](file_contents):
            result['status'] = 'PASS'
            result['exit_code'] = 0
            print('  PASS: verification succeeded')
        else:
            result['status'] = 'FAIL'
            result['exit_code'] = 1
            print(
                f'  FAIL: verification failed. Files found: {list(file_contents.keys())}'
            )

    except Exception as e:
        result['error'] = str(e)
        result['status'] = 'EXCEPTION'
        result['exit_code'] = 99
        print(f'  EXCEPTION: {e}')
        traceback.print_exc()

    finally:
        result['elapsed'] = time.time() - start
        try:
            await client.close()
        except Exception:
            pass

    return result


async def main() -> int:
    task_indices_env = os.environ.get('APP_TASK_INDICES', '')
    if task_indices_env:
        indices = [int(i) for i in task_indices_env.split(',') if i.strip()]
        tasks = [TASKS[i] for i in indices if i < len(TASKS)]
    else:
        tasks = TASKS

    print('\nApp SWE Task Test Runner')
    print(f'Server: {BASE_URL}')
    print(f'Timeout per task: {WAIT_SECONDS}s')
    print(f'Tasks: {[t["name"] for t in tasks]}\n')

    # Check server health first
    import urllib.request

    try:
        with urllib.request.urlopen(  # noqa: ASYNC210
            f'{BASE_URL}/api/health/live', timeout=5
        ) as r:
            print(f'Server health: {r.status} OK\n')
    except Exception as e:
        print(f'Server not reachable: {e}')
        return 10

    results = []
    for task in tasks:
        client = AppClient(BASE_URL)
        r = await run_task(task, client)
        results.append(r)

    # Summary
    print(f'\n{"=" * 70}')
    print('RESULTS SUMMARY')
    print(f'{"=" * 70}')
    passed = 0
    for r in results:
        status_sym = 'PASS' if r['status'] == 'PASS' else 'FAIL'
        print(
            f'  {status_sym}  {r["name"]:<28}  {r["status"]:<12}  '
            f'{r["elapsed"]:5.1f}s  state={r["last_state"]}'
        )
        if r['status'] == 'PASS':
            passed += 1
    print(f'\n  {passed}/{len(results)} tasks passed')
    print(f'{"=" * 70}\n')

    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
