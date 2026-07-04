"""Tests for synthesized goal context used in compaction."""

from __future__ import annotations

from unittest.mock import patch

from backend.context.context_pipeline.goal_context import (
    build_goal_context_for_compaction,
    strip_verbatim_user_echo,
)


def test_build_goal_context_excludes_verbatim_user_messages():
    snapshot = {
        'user_messages': [{'text': 'A' * 200}],
        'task_plan': {
            'tasks': [
                {'status': 'in_progress', 'description': 'Wire compaction pipeline'},
            ]
        },
    }
    goal = build_goal_context_for_compaction(snapshot=snapshot)
    assert 'A' * 50 not in goal
    assert 'Wire compaction pipeline' in goal or 'Active scope' in goal


def test_strip_verbatim_user_echo_replaces_echoed_goal():
    long_user = (
        'Please refactor the entire context pipeline to stop double compaction '
        'and never echo user messages verbatim in summaries ever again.'
    )
    snapshot = {'user_messages': [{'text': long_user}]}
    summary = '## USER GOAL\n' + long_user + '\n\n## NEXT STEPS\n- continue'
    with patch(
        'backend.context.context_pipeline.goal_context.build_goal_context_for_compaction',
        return_value='- Objective: Refactor compaction pipeline',
    ):
        cleaned = strip_verbatim_user_echo(summary, snapshot=snapshot)
    assert long_user not in cleaned
    assert 'Refactor compaction pipeline' in cleaned


def test_group_events_by_api_round_splits_on_actions():
    from backend.context.context_pipeline.grouping import group_events_by_api_round
    from backend.ledger.action.message import MessageAction
    from backend.ledger.observation.commands import CmdOutputObservation

    action1 = MessageAction(content='run tests')
    action1.id = 1
    obs1 = CmdOutputObservation(content='ok', command='pytest', metadata={})
    obs1.id = 2
    action2 = MessageAction(content='done')
    action2.id = 3
    groups = group_events_by_api_round([action1, obs1, action2])
    assert len(groups) == 2
    assert groups[0] == [action1, obs1]
    assert groups[1] == [action2]
