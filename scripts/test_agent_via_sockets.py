import asyncio
import os
import random
import subprocess
import sys
import time
from typing import Any

# Ensure backend and client are importable from repo root
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from client import AppClient


def _build_scenarios() -> list[dict[str, Any]]:
    """Return ambiguous multi-capability challenge scenarios."""
    return [
        {
            'name': 'checkpoint_restore_loop',
            'primary_file': 'agent_capability_test.txt',
            'capabilities': (
                'file_create',
                'checkpoint_save',
                'checkpoint_restore',
                'working_memory',
            ),
            'prompt': (
                'You are running a resilience drill with partial requirements.\n'
                "Goal: leave the workspace in a 'safe baseline' state.\n\n"
                'Tasks (decide exact order if needed, but explain brief rationale):\n'
                "1) Create 'agent_capability_test.txt' with content: Initial state\n"
                '2) Save a checkpoint for this baseline.\n'
                '3) Change the file content to: State updated by experiment\n'
                '4) Add a concise working-memory note that includes: Test completed successfully\n'
                '5) Restore the checkpoint so the file ends at Initial state.\n\n'
                'Constraint: if any instruction conflicts with safety or tool limits, choose the safest valid path and continue.'
            ),
        },
        {
            'name': 'multi_file_triage',
            'primary_file': 'triage_summary.md',
            'capabilities': (
                'file_create',
                'file_edit',
                'workspace_read',
                'reasoned_planning',
            ),
            'prompt': (
                'Treat this as an ambiguous incident triage.\n'
                'You need to leave a compact handoff artifact.\n\n'
                "1) Create 'triage_notes.txt' with 3 plausible root-cause hypotheses.\n"
                '2) Read one existing repository file of your choice that helps disambiguate.\n'
                "3) Create 'triage_summary.md' with sections: Findings, Uncertainties, Next Safe Step.\n"
                '4) Update the summary once after re-evaluating your own assumptions.\n\n'
                'If uncertain, state assumptions explicitly rather than guessing.'
            ),
        },
        {
            'name': 'tooling_judgement',
            'primary_file': 'agent_judgement_report.txt',
            'capabilities': (
                'search_tools',
                'choose_actions_under_uncertainty',
                'state_tracking',
            ),
            'prompt': (
                'Capability stress test with deliberate ambiguity:\n'
                '- You may use checkpointing, but only if it helps recoverability.\n'
                '- You should avoid unnecessary writes.\n\n'
                'Outcome requirements:\n'
                "1) Produce 'agent_judgement_report.txt' with:\n"
                '   - chosen strategy,\n'
                '   - one discarded strategy,\n'
                '   - why your final approach is safer.\n'
                '2) If you use checkpoint, document why in the report.\n'
                '3) Add a short working-memory note marking completion.\n\n'
                'Prefer reversible actions when confidence is low.'
            ),
        },
        {
            'name': 'rollback_decision_test',
            'primary_file': 'decision_log.json',
            'capabilities': (
                'structured_output',
                'checkpoint_optional',
                'edit_after_review',
            ),
            'prompt': (
                'Run a decision-quality exercise.\n'
                "1) Create 'decision_log.json' with fields: scenario, assumptions, actions, confidence.\n"
                '2) Add at least 2 actions where one is reversible and one is not.\n'
                '3) Re-read the file and reduce overconfidence if needed.\n'
                '4) If confidence < 0.7, prefer a reversible final action and mention rollback considerations.\n\n'
                'Keep the final JSON valid.'
            ),
        },
    ]


def _choose_scenario() -> dict[str, Any]:
    """Pick a scenario by index or pseudo-random seed."""
    scenarios = _build_scenarios()
    forced_index = os.environ.get('APP_SCENARIO_INDEX')
    if forced_index is not None and forced_index.strip():
        idx = int(forced_index) % len(scenarios)
        return scenarios[idx]

    seed_value = os.environ.get('APP_SCENARIO_SEED')
    rng = random.Random(seed_value) if seed_value else random.Random()
    return rng.choice(scenarios)


def _run_batch_mode() -> int:
    """Run multiple scenarios by re-invoking this script per scenario.

    Env:
        APP_BATCH_SCENARIOS=all|N   (default: all)
        APP_BATCH_SEED=<seed>       (optional shuffle seed)
    """
    scenarios = _build_scenarios()
    raw = (os.environ.get('APP_BATCH_SCENARIOS', 'all') or 'all').strip().lower()

    if raw == 'all':
        run_count = len(scenarios)
    else:
        try:
            run_count = max(1, min(int(raw), len(scenarios)))
        except ValueError:
            print(f"Invalid APP_BATCH_SCENARIOS={raw!r}; expected 'all' or integer.")
            return 9

    indices = list(range(len(scenarios)))
    batch_seed = os.environ.get('APP_BATCH_SEED')
    if batch_seed:
        random.Random(batch_seed).shuffle(indices)

    selected = indices[:run_count]
    print(f'Batch mode: running {run_count} scenario(s)')
    print('Order:', ', '.join(f'{i}:{scenarios[i]["name"]}' for i in selected))

    results: list[tuple[int, str, int, float]] = []
    worst_code = 0

    for pos, idx in enumerate(selected, start=1):
        name = scenarios[idx]['name']
        print('\n' + '=' * 72)
        print(f'[{pos}/{run_count}] Scenario {idx}: {name}')
        print('=' * 72)

        env = dict(os.environ)
        env['APP_SCENARIO_INDEX'] = str(idx)
        env['APP_BATCH_SCENARIOS'] = '0'  # prevent recursion

        started = time.time()
        completed = subprocess.run([sys.executable, __file__], env=env, check=False)
        elapsed = time.time() - started
        code = int(completed.returncode)
        worst_code = max(worst_code, code)
        results.append((idx, name, code, elapsed))

    print('\nBatch summary:')
    print('-' * 72)
    for idx, name, code, elapsed in results:
        status = 'PASS' if code == 0 else 'FAIL'
        print(f'{status:4}  idx={idx:<2}  code={code:<2}  time={elapsed:6.1f}s  {name}')
    print('-' * 72)
    passed = sum(1 for _, _, c, _ in results if c == 0)
    print(f'Passed {passed}/{len(results)} scenarios')

    return worst_code


async def main() -> int:
    base_url = os.environ.get('APP_BASE_URL', 'http://localhost:3000')
    print(f'Connecting to local App server at {base_url}...')

    client = AppClient(base_url)

    scenario = _choose_scenario()
    test_file_name = str(scenario['primary_file'])
    test_file = os.path.join(os.path.abspath(os.path.dirname(__file__)), test_file_name)
    print(f'Selected scenario: {scenario["name"]}')
    print(f'Expected capability mix: {", ".join(scenario["capabilities"])}')
    agent_workspace_file_path: str | None = None
    if os.path.exists(test_file):
        os.remove(test_file)

    exit_code = 1
    terminal_reached = False
    saw_finish_event = False

    try:
        # Create or reuse a conversation
        # NOTE: Using APP_CONVERSATION_ID in a shared shell can be "sticky" across runs.
        # To avoid accidentally reusing a conversation that still has an active agent loop,
        # reuse is opt-in via APP_REUSE_CONVERSATION_ID.
        conv_id = os.environ.get('APP_REUSE_CONVERSATION_ID')
        if conv_id:
            print(f'Reusing conversation: {conv_id}')
        else:
            print('Creating conversation...')
            # Guard against occasional hangs by bounding the await.
            conv = await asyncio.wait_for(client.create_conversation(), timeout=60)
            print('Conv object:', conv)
            conv_id = conv.get('id') or conv.get('conversation_id')
            if not conv_id:
                raise ValueError(f'Could not find conversation ID in: {conv}')
            print(f'Created conversation: {conv_id}')

        skip_start = os.environ.get('APP_SKIP_START_AGENT', '').strip().lower() in {
            '1',
            'true',
            'yes',
            'on',
        }
        if skip_start:
            print('Skipping start_agent (APP_SKIP_START_AGENT=1)')
        else:
            print('Starting agent...')
            await asyncio.wait_for(client.start_agent(str(conv_id)), timeout=60)

        initialized = asyncio.Event()
        terminal = asyncio.Event()
        verbose = os.environ.get('APP_VERBOSE_EVENTS', '').strip().lower() in {
            '1',
            'true',
            'yes',
            'on',
        }
        last_agent_state: str | None = None

        def _safe_preview(value: Any, limit: int = 200) -> str:
            if not value:
                return ''
            if isinstance(value, str):
                return value.replace('\n', ' ')[:limit]
            return str(value)[:limit]

        def _agent_state(event: dict) -> str:
            extras = event.get('extras') or {}
            if isinstance(extras, dict):
                state = extras.get('agent_state')
                if isinstance(state, str) and state:
                    return state.upper()
            return ''

        def _is_initialized_event(event: dict) -> bool:
            # "Real" event-stream events carry an id; the server can also emit
            # a synthetic default state on connection without one.
            return bool(
                event.get('id') is not None
                and _agent_state(event) == 'AWAITING_USER_INPUT'
            )

        def _is_terminal_event(event: dict) -> bool:
            state = _agent_state(event)
            if state in {
                'FINISHED',
                'STOPPED',
                'ERROR',
                'REJECTED',
                'AWAITING_USER_CONFIRMATION',
            }:
                return True
            action = event.get('action')
            observation = event.get('observation')
            return action == 'finish' or observation in {'agent_finish'}

        async def on_event(event: dict) -> None:
            nonlocal last_agent_state
            nonlocal agent_workspace_file_path
            nonlocal saw_finish_event

            event_id = event.get('id')
            action = event.get('action')
            observation = event.get('observation')
            evt_type = event.get('type')
            status_update = event.get('status_update')
            state = _agent_state(event)
            if event.get('action') == 'streaming_chunk':
                print('GOT STREAMING CHUNK')
            if event.get('action') == 'streaming_chunk':
                print('CHUNK', repr(event)[:50])
            if state:
                last_agent_state = state

            msg = event.get('message') or event.get('content')
            head = (
                state
                or observation
                or action
                or evt_type
                or ('status' if status_update else 'event')
            )
            tail = _safe_preview(msg)
            print(f'[EVENT] {head} id={event_id} {tail}')

            if action == 'finish' or observation == 'agent_finish':
                saw_finish_event = True

            # Capture path from agent workspace tool output like:
            # "I wrote to the file /workspace/agent_capability_test.txt."
            if isinstance(msg, str) and f'/workspace/{test_file_name}' in msg:
                marker = f'/workspace/{test_file_name}'
                start = msg.find(marker)
                if start != -1:
                    agent_workspace_file_path = msg[start : start + len(marker)]

            # Surface rich data for debugging error classification.
            if verbose or head in {'ERROR', 'REJECTED'}:
                extras = event.get('extras')
                if extras:
                    print(f'        extras={extras}')
                if event.get('status') is not None:
                    print(f'        status={event.get("status")}')
                if event.get('error') is not None:
                    print(f'        error={event.get("error")}')

            if _is_initialized_event(event):
                initialized.set()
            if _is_terminal_event(event):
                terminal.set()

        print('Joining Socket.IO conversation stream...')
        await client.join_conversation(conversation_id=str(conv_id), on_event=on_event)
        await asyncio.sleep(0.5)

        print(f'Socket.IO connected: {client.is_ws_connected}')

        # Wait for the server to finish initializing the conversation.
        # This avoids a race where AWAITING_USER_INPUT overrides RUNNING.
        init_timeout = int(os.environ.get('APP_INIT_TIMEOUT', '60'))
        try:
            await asyncio.wait_for(initialized.wait(), timeout=init_timeout)
        except TimeoutError:
            print(
                f'Warning: server did not reach awaiting_user_input within {init_timeout}s. '
                f'Continuing anyway (last_agent_state={last_agent_state}).'
            )

        prompt = str(scenario['prompt'])

        print('Sending prompt...')
        print(f'Socket.IO connected (pre-send): {client.is_ws_connected}')
        await client.send_message(prompt)
        await asyncio.sleep(0.1)
        print(f'Socket.IO connected (post-send): {client.is_ws_connected}')

        wait_seconds = int(os.environ.get('APP_WAIT_SECONDS', '300'))
        print(
            f'Waiting for agent to process ({wait_seconds}s or until terminal state)...'
        )
        try:
            await asyncio.wait_for(terminal.wait(), timeout=wait_seconds)
            terminal_reached = True
        except TimeoutError:
            print(f'\nTimed out after {wait_seconds}s without a terminal agent state.')
            exit_code = 2

        if os.path.exists(test_file):
            with open(test_file, 'r', encoding='utf-8') as f:  # noqa: ASYNC230
                final = f.read()
            print(f'\nFinal file contents ({test_file_name}):')
            print(final)
            if terminal_reached and last_agent_state in {'ERROR', 'REJECTED'}:
                print(f'\nTest failed: terminal agent state is {last_agent_state}.')
                exit_code = 3
            elif terminal_reached and saw_finish_event:
                print('\nTest passed: finish event observed with file evidence.')
                exit_code = 0
            elif terminal_reached and last_agent_state in {'FINISHED', 'STOPPED'}:
                print('\nTest passed: local file created and terminal state reached.')
                exit_code = 0
            elif terminal_reached and last_agent_state == 'AWAITING_USER_CONFIRMATION':
                print(
                    '\nTest incomplete: agent is awaiting user confirmation '
                    'for a high-impact action.'
                )
                exit_code = 6
            elif terminal_reached:
                print(
                    f'\nTest inconclusive: terminal state {last_agent_state!r} '
                    'with local file present.'
                )
                exit_code = 4
        elif agent_workspace_file_path:
            print(
                f'\n{test_file_name} was created in the agent workspace '
                f'at: {agent_workspace_file_path}'
            )
            print(
                'Note: this test runs the agent in an isolated /workspace, '
                'not your repo root.'
            )
            if terminal_reached and last_agent_state in {'ERROR', 'REJECTED'}:
                print(f'\nTest failed: terminal agent state is {last_agent_state}.')
                exit_code = 3
            elif terminal_reached and saw_finish_event:
                print(
                    '\nTest passed: finish event observed with workspace file evidence.'
                )
                exit_code = 0
            elif terminal_reached and last_agent_state in {'FINISHED', 'STOPPED'}:
                print(
                    '\nTest passed: workspace file evidence found and terminal state reached.'
                )
                exit_code = 0
            elif terminal_reached and last_agent_state == 'AWAITING_USER_CONFIRMATION':
                print(
                    '\nTest incomplete: agent is awaiting user confirmation '
                    'for a high-impact action.'
                )
                exit_code = 6
            elif terminal_reached:
                print(
                    f'\nTest inconclusive: terminal state {last_agent_state!r} '
                    'with workspace file evidence.'
                )
                exit_code = 4
        else:
            print(f'\n{test_file_name} was not created.')
            if terminal_reached and last_agent_state in {'ERROR', 'REJECTED'}:
                print(f'\nTest failed: terminal agent state is {last_agent_state}.')
                exit_code = 3
            elif terminal_reached:
                if last_agent_state == 'AWAITING_USER_CONFIRMATION':
                    print(
                        '\nTest incomplete: agent is awaiting user confirmation '
                        'for a high-impact action.'
                    )
                    exit_code = 6
                    return exit_code
                print(
                    f'\nTest failed: terminal state {last_agent_state!r} '
                    'but no file creation evidence.'
                )
                exit_code = 5

    finally:
        try:
            await client.leave_conversation()
        except Exception:
            pass
        await client.close()
    return exit_code


if __name__ == '__main__':
    batch_requested = os.environ.get('APP_BATCH_SCENARIOS')
    if batch_requested and batch_requested.strip() not in {'', '0', 'false', 'False'}:
        sys.exit(_run_batch_mode())
    sys.exit(asyncio.run(main()))
