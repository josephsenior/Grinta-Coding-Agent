"""Task-level end-to-end regression for the CLI."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _sitecustomize_source() -> str:
    return textwrap.dedent(
        """
        from __future__ import annotations

        import asyncio
        from types import SimpleNamespace

        import backend.core.bootstrap.agent_control_loop as agent_loop
        import backend.core.bootstrap.setup as bootstrap_setup
        from backend.core.schemas import AgentState
        from backend.ledger import EventSource, EventStreamSubscriber
        from backend.ledger.action import MessageAction
        from backend.ledger.observation.agent import AgentStateChangedObservation


        _SEEN_TASKS: list[str] = []


        class _FakeController:
            def __init__(self) -> None:
                self._state = AgentState.AWAITING_USER_INPUT

            def get_agent_state(self):
                return self._state

            async def set_agent_state_to(self, state):
                self._state = state

            def step(self) -> None:
                return None

            def save_state(self) -> None:
                return None


        def _create_controller(agent, runtime, config, conversation_stats, replay_events=None):
            del agent, config, conversation_stats, replay_events

            def _capture(event):
                if isinstance(event, MessageAction) and getattr(event, 'source', None) == EventSource.USER:
                    _SEEN_TASKS.append(event.content)

            runtime.event_stream.subscribe(
                EventStreamSubscriber.TEST,
                _capture,
                'cli-task-capture',
            )
            return _FakeController(), SimpleNamespace()


        async def _run_agent_until_done(controller, runtime, memory, end_states):
            del memory, end_states
            for _ in range(100):
                if _SEEN_TASKS:
                    break
                await asyncio.sleep(0.01)
            if not _SEEN_TASKS:
                raise AssertionError('CLI task was never observed by the fake task loop')

            answer = MessageAction(
                content='Task complete: summarized README.md for the CLI regression.',
                wait_for_response=True,
            )
            answer.source = EventSource.AGENT
            runtime.event_stream.add_event(answer, EventSource.AGENT)
            controller._state = AgentState.AWAITING_USER_INPUT
            runtime.event_stream.add_event(
                AgentStateChangedObservation('', AgentState.AWAITING_USER_INPUT),
                EventSource.AGENT,
            )


        bootstrap_setup.create_controller = _create_controller
        agent_loop.run_agent_until_done = _run_agent_until_done
        """
    )


@pytest.mark.integration
def test_launch_entry_completes_one_task_via_subprocess(tmp_path: Path) -> None:
    project_root = tmp_path / 'project'
    project_root.mkdir()
    (project_root / 'README.md').write_text('CLI task regression target\n', encoding='utf-8')

    hook_dir = tmp_path / 'hooks'
    hook_dir.mkdir()
    (hook_dir / 'sitecustomize.py').write_text(
        _sitecustomize_source(), encoding='utf-8'
    )

    env = os.environ.copy()
    env['LLM_API_KEY'] = 'sk-test-cli-task'
    env['LLM_MODEL'] = 'openai/gpt-4.1'
    env['GRINTA_NO_SPLASH'] = '1'
    env['LOG_TO_FILE'] = 'false'
    env['PYTHONUTF8'] = '1'
    env['HOME'] = str(tmp_path)
    env['USERPROFILE'] = str(tmp_path)
    existing_path = env.get('PYTHONPATH', '')
    path_parts = [str(hook_dir), str(_REPO_ROOT)]
    if existing_path:
        path_parts.append(existing_path)
    env['PYTHONPATH'] = os.pathsep.join(path_parts)

    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'launch.entry',
            '--project',
            str(project_root),
            '--no-splash',
        ],
        input='Summarize README.md in one sentence.\n',
        text=True,
        capture_output=True,
        encoding='utf-8',
        errors='replace',
        cwd=_REPO_ROOT,
        env=env,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert 'Summarize README.md in one sentence.' in result.stdout
    assert 'Task complete: summarized README.md for the CLI regression.' in result.stdout
    assert 'Initialization failed' not in result.stdout