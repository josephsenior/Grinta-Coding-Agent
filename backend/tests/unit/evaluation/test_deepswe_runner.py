from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.deepswe.run_grinta import (
    _benchmark_user_response,
    _capture_patch,
    _extract_metrics,
    _find_authentication_error,
    _find_subscription_usage_limit,
    _load_instruction,
    _materialize_submission_head,
    _parser,
    _validate_subscription_model,
)


def test_shared_preflight_bypasses_legacy_model_defaults(tmp_path, monkeypatch, capsys):
    from evaluation.deepswe import run_grinta, shared_task

    monkeypatch.setattr(
        shared_task, 'load_shared_task', lambda p: {'identity': {'task_id': 'shared'}}
    )
    monkeypatch.setattr(
        shared_task,
        'preflight_manifest',
        lambda *a: {'model': None, 'live_model_calls': 0},
    )
    monkeypatch.setattr(
        run_grinta,
        '_validate_subscription_model',
        lambda *a: pytest.fail('legacy model settings used'),
    )
    assert (
        run_grinta.main(
            [
                '--workspace',
                str(tmp_path),
                '--shared-task',
                'task.json',
                '--task-id',
                'shared',
                '--grinta-commit',
                'a' * 40,
                '--output-dir',
                str(tmp_path / 'output'),
                '--dry-run',
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)['model'] is None
    assert not (tmp_path / 'output').exists()


def test_shared_record_cannot_start_live_model(tmp_path, monkeypatch):
    from evaluation.deepswe import run_grinta, shared_task

    monkeypatch.setattr(
        shared_task, 'load_shared_task', lambda p: {'identity': {'task_id': 'shared'}}
    )
    with pytest.raises(SystemExit, match='live execution is deferred'):
        run_grinta.main(
            [
                '--workspace',
                str(tmp_path),
                '--shared-task',
                'task.json',
                '--task-id',
                'shared',
                '--grinta-commit',
                'a' * 40,
                '--output-dir',
                str(tmp_path / 'output'),
            ]
        )


def test_shared_record_rejects_different_task_id(tmp_path, monkeypatch):
    from evaluation.deepswe import run_grinta, shared_task

    monkeypatch.setattr(
        shared_task, 'load_shared_task', lambda p: {'identity': {'task_id': 'shared'}}
    )
    with pytest.raises(SystemExit, match='Task ID disagrees'):
        run_grinta.main(
            [
                '--workspace',
                str(tmp_path),
                '--shared-task',
                'task.json',
                '--task-id',
                'another',
                '--grinta-commit',
                'a' * 40,
                '--output-dir',
                str(tmp_path / 'output'),
                '--dry-run',
            ]
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True)


def test_capture_patch_includes_tracked_untracked_and_committed_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'benchmark@example.invalid')
    _git(repo, 'config', 'user.name', 'Benchmark Test')
    tracked = repo / 'tracked.txt'
    tracked.write_text('before\n', encoding='utf-8')
    _git(repo, 'add', 'tracked.txt')
    _git(repo, 'commit', '-m', 'baseline')
    baseline = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    tracked.write_text('after\n', encoding='utf-8')
    _git(repo, 'add', 'tracked.txt')
    _git(repo, 'commit', '-m', 'agent commit')
    (repo / 'untracked.txt').write_text('new\n', encoding='utf-8')
    patch = _capture_patch(repo, baseline)

    assert 'tracked.txt' in patch
    assert 'untracked.txt' in patch
    assert '+after' in patch
    assert '+new' in patch
    assert subprocess.run(
        ['git', 'status', '--short'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines() == ['?? untracked.txt']


def test_materialize_submission_head_packages_uncommitted_workspace(
    tmp_path: Path,
) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'benchmark@example.invalid')
    _git(repo, 'config', 'user.name', 'Benchmark Test')
    tracked = repo / 'tracked.txt'
    tracked.write_text('before\n', encoding='utf-8')
    _git(repo, 'add', 'tracked.txt')
    _git(repo, 'commit', '-m', 'baseline')
    baseline = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    tracked.write_text('after\n', encoding='utf-8')
    (repo / 'new.txt').write_text('new\n', encoding='utf-8')
    patch = _capture_patch(repo, baseline)

    result = _materialize_submission_head(repo, baseline, patch)

    assert result['mode'] == 'synthetic_commit'
    assert result['synthetic_commit'] is True
    assert result['head'] != baseline
    committed = subprocess.run(
        ['git', 'diff', '--binary', '--no-ext-diff', baseline, 'HEAD'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert committed == patch


def test_materialize_submission_head_preserves_agent_commit(tmp_path: Path) -> None:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init')
    _git(repo, 'config', 'user.email', 'benchmark@example.invalid')
    _git(repo, 'config', 'user.name', 'Benchmark Test')
    tracked = repo / 'tracked.txt'
    tracked.write_text('before\n', encoding='utf-8')
    _git(repo, 'add', 'tracked.txt')
    _git(repo, 'commit', '-m', 'baseline')
    baseline = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    tracked.write_text('after\n', encoding='utf-8')
    _git(repo, 'add', 'tracked.txt')
    _git(repo, 'commit', '-m', 'agent commit')
    agent_head = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    patch = _capture_patch(repo, baseline)

    result = _materialize_submission_head(repo, baseline, patch)

    assert result == {
        'mode': 'agent_commit',
        'head': agent_head,
        'synthetic_commit': False,
    }


def test_extract_metrics_does_not_infer_a_verdict() -> None:
    combined = SimpleNamespace(accumulated_cost=1.25)
    state = SimpleNamespace(
        agent_state='finished',
        iteration_flag=SimpleNamespace(current_value=12),
        conversation_stats=SimpleNamespace(
            get_combined_metrics=lambda: combined,
        ),
    )

    assert _extract_metrics(state) == {
        'agent_state': 'finished',
        'turn_count': 12,
        'cost_usd': 1.25,
    }


def test_load_instruction_rejects_blank_text() -> None:
    args = argparse.Namespace(instruction_file=None, instruction='  ')

    try:
        _load_instruction(args)
    except ValueError as exc:
        assert str(exc) == 'task instruction must not be empty'
    else:
        raise AssertionError('blank instruction was accepted')


def test_protocol_defaults_freeze_sol_xhigh() -> None:
    parser = _parser()
    args = parser.parse_args(
        [
            '--workspace',
            'repo',
            '--instruction',
            'fix it',
            '--task-id',
            'task',
            '--grinta-commit',
            'a' * 40,
            '--output-dir',
            'out',
        ]
    )

    assert args.model == 'codex/gpt-5.6-sol'
    assert args.reasoning_effort == 'xhigh'


def test_subscription_protocol_rejects_usage_billed_provider() -> None:
    _validate_subscription_model('codex/gpt-5.6-sol')

    try:
        _validate_subscription_model('openai/gpt-5.6-sol')
    except ValueError as exc:
        assert 'subscription-only' in str(exc)
    else:
        raise AssertionError('usage-billed OpenAI API transport was accepted')


def test_benchmark_exits_instead_of_restarting_after_subscription_quota() -> None:
    quota = SimpleNamespace(
        error_category='daily_quota', content='Subscription usage limit reached'
    )
    state = SimpleNamespace(history=[quota])

    assert _find_subscription_usage_limit(state) == quota.content
    assert _benchmark_user_response(state) == '/exit'


def test_benchmark_exits_instead_of_restarting_after_authentication_error() -> None:
    auth = SimpleNamespace(error_category='auth', content='ChatGPT sign-in required')
    state = SimpleNamespace(history=[auth])

    assert _find_authentication_error(state) == auth.content
    assert _benchmark_user_response(state) == '/exit'
