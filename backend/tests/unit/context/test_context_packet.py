"""Tests for prompt-facing context packet assembly."""

from __future__ import annotations

from types import SimpleNamespace

from backend.context.canonical_state import CanonicalTaskState, save_canonical_state
from backend.context.prompt.context_packet import (
    CONTEXT_PACKET_MARKER,
    build_context_packet,
    build_context_packet_observation,
)
from backend.ledger.action import CmdRunAction, MessageAction, TaskTrackingAction
from backend.ledger.event import EventSource
from backend.ledger.observation import CmdOutputObservation
from backend.ledger.observation.agent import AgentCondensationObservation


def _user(text: str, event_id: int) -> MessageAction:
    event = MessageAction(content=text)
    event.source = EventSource.USER
    event.id = event_id
    return event


def _cmd(command: str, event_id: int) -> CmdRunAction:
    event = CmdRunAction(command=command)
    event.id = event_id
    return event


def _output(
    command: str, content: str, event_id: int, exit_code: int
) -> CmdOutputObservation:
    event = CmdOutputObservation(content=content, command=command, exit_code=exit_code)
    event.id = event_id
    return event


def _tasks(task_list: list[dict], event_id: int) -> TaskTrackingAction:
    event = TaskTrackingAction(command='update', task_list=task_list)
    event.id = event_id
    return event


def test_context_packet_contains_one_canonical_state_and_latest_verification(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [
        _user('Fix memory compaction', 1),
        _cmd('pytest backend/tests/unit/context', 2),
        _output('pytest backend/tests/unit/context', '7 passed', 3, 0),
    ]

    packet = build_context_packet(
        events,
        events,
        state=SimpleNamespace(),
        char_budget=1800,
    )

    assert packet is not None
    assert packet.content.count(CONTEXT_PACKET_MARKER) == 2
    assert packet.content.count('<CANONICAL_TASK_STATE>') == 2
    assert 'MessageAction id=1' not in packet.content
    assert 'Latest verification: PASSED' in packet.content
    assert len(packet.content) <= 1800


def test_context_packet_omits_redundant_user_context_and_stale_objective(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [
        _user('hey, are you powerful?', 1),
        _user('make a deep analysis on this project', 2),
        _user('continue', 3),
    ]

    packet = build_context_packet(events, events, char_budget=2200)

    assert packet is not None
    assert 'RECENT_USER_REQUEST_CONTEXT' not in packet.content
    assert '- Objective: hey, are you powerful?' not in packet.content
    assert '- Latest directive: continue' not in packet.content


def test_context_packet_omits_request_context_when_latest_user_turn_is_raw_prompt(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [_user('Implement the exporter', 1)]

    packet = build_context_packet(events, events, char_budget=1800)

    assert packet is not None
    assert 'RECENT_USER_REQUEST_CONTEXT' not in packet.content


def test_recent_causal_tail_omits_chat_messages_already_in_prompt(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [
        _user('continue', 929),
        _cmd('python -m pytest backend/tests/unit/context', 930),
    ]

    packet = build_context_packet(events, events, char_budget=1800)

    assert packet is not None
    assert 'RECENT_CAUSAL_TAIL' in packet.content
    assert 'MessageAction id=929' not in packet.content
    assert 'continue' not in packet.content
    assert 'CmdRunAction id=930: python -m pytest backend/tests/unit/context' in (
        packet.content
    )


def test_recent_causal_tail_keeps_latest_progress_after_chat_burst(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    command = _cmd('python -m pytest backend/tests/unit/context', 100)
    events = [
        command,
        *[_user(f'continue {index}', 200 + index) for index in range(12)],
    ]

    packet = build_context_packet(events, events, char_budget=1800)

    assert packet is not None
    assert 'CmdRunAction id=100: python -m pytest backend/tests/unit/context' in (
        packet.content
    )
    assert 'MessageAction id=211' not in packet.content


def test_context_packet_uses_snapshot_user_turns_for_compacted_continue(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    monkeypatch.setattr(
        'backend.context.prompt.context_packet.load_snapshot',
        lambda state=None: {
            'recent_user_messages': [
                {'event_id': 12, 'text': 'Audit the runtime loop'},
                {'event_id': 13, 'text': 'continue'},
            ]
        },
    )
    events = [_user('continue', 13)]

    packet = build_context_packet(
        events,
        events,
        state=SimpleNamespace(),
        char_budget=1800,
    )

    assert packet is not None
    assert 'Preserved user messages not otherwise in prompt:' in packet.content
    assert '- id=12: Audit the runtime loop' in packet.content
    assert '- id=13: continue' not in packet.content


def test_context_packet_prioritizes_task_checkpoint_after_compaction(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [
        _user('Build a small raft demo', 1),
        _tasks(
            [
                {'description': 'Create message modules', 'status': 'done'},
                {'description': 'Implement node.py', 'status': 'in_progress'},
                {'description': 'Implement cluster.py', 'status': 'todo'},
            ],
            2,
        ),
    ]

    packet = build_context_packet(events, events, just_compacted=True, char_budget=2200)

    assert packet is not None
    assert 'OPERATIONAL_CHECKPOINT' in packet.content
    assert 'Next action: Implement node.py' in packet.content
    assert 'remaining: Implement cluster.py' in packet.content


def test_context_packet_ignores_old_packets_as_validated_summaries(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    old_packet = AgentCondensationObservation(
        content=f'{CONTEXT_PACKET_MARKER}\nstale packet\n{CONTEXT_PACKET_MARKER}',
        is_working_set=True,
    )
    old_packet.id = 1
    summary = AgentCondensationObservation(
        content='# State Summary\nCurrent real summary'
    )
    summary.id = 2
    user = _user('Continue the task', 3)

    packet = build_context_packet([user], [old_packet, summary, user], char_budget=1800)

    assert packet is not None
    assert 'Current real summary' in packet.content
    assert 'stale packet' not in packet.content


def test_context_packet_observation_is_marked_as_working_set(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    events = [_user('Build packet', 1)]

    observation = build_context_packet_observation(events, events)

    assert observation is not None
    assert observation.is_working_set is True
    assert CONTEXT_PACKET_MARKER in observation.content


def test_repeated_compaction_replay_keeps_one_current_state(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    stale_packets = []
    for index in range(5):
        event = AgentCondensationObservation(
            content=(
                f'{CONTEXT_PACKET_MARKER}\n'
                f'stale packet {index}\n'
                'resuming task\n'
                f'{CONTEXT_PACKET_MARKER}'
            ),
            is_working_set=True,
        )
        event.id = index + 1
        stale_packets.append(event)
    restore_noise = AgentCondensationObservation(
        content='<POST_COMPACT_RESTORE>\nold restore block\n</POST_COMPACT_RESTORE>',
        is_working_set=True,
    )
    restore_noise.id = 10
    user = _user('Finish the context packet hardening', 11)
    command = _cmd('pytest backend/tests/unit/context/test_context_packet.py', 12)
    output = _output(
        'pytest backend/tests/unit/context/test_context_packet.py',
        '4 passed',
        13,
        0,
    )

    packet = build_context_packet(
        [user, command, output],
        [*stale_packets, restore_noise, user, command, output],
        char_budget=2200,
    )

    assert packet is not None
    assert packet.content.count('<CANONICAL_TASK_STATE>') == 2
    assert packet.content.count('Latest verification: PASSED') == 1
    assert 'MessageAction id=11' not in packet.content
    assert 'stale packet' not in packet.content
    assert 'old restore block' not in packet.content
    assert 'resuming task' not in packet.content


def test_large_context_model_expands_context_packet_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'backend.context.canonical_state.canonical_state_path',
        lambda state=None: tmp_path / 'canonical_task_state.json',
    )
    canonical = CanonicalTaskState(
        objective='Keep long-session coding continuity stable',
        latest_directive='Implement the context pipeline hardening',
        next_action='Continue from canonical state without rereading old files',
        narrative_summary='Detailed verified state. ' * 1200,
    )
    save_canonical_state(canonical)
    llm_config = SimpleNamespace(
        model='openai/gpt-5',
        context_window_tokens=400_000,
        max_output_tokens=128_000,
        max_input_tokens=None,
    )

    packet = build_context_packet([], [], llm_config=llm_config, char_budget=6_000)

    assert packet is not None
    assert len(packet.content) > 4_000
    assert len(packet.content) <= 32_000
    assert 'Continue from canonical state' in packet.content
