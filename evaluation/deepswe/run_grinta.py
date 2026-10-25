"""Run normal headless Grinta in one externally prepared benchmark workspace.

This module deliberately does not score the result. DeepSWE's external verifier is
the sole source of PASS/FAIL; Grinta's terminal state is retained only as a
diagnostic signal.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

_DEFAULT_CONFIG = Path(__file__).with_name('config.json')
_SUBSCRIPTION_MODEL_PREFIX = 'codex/'
_QUOTA_ERROR_CATEGORY = 'daily_quota'
_AUTH_ERROR_CATEGORY = 'auth'


class SubscriptionUsageLimitError(RuntimeError):
    """The ChatGPT subscription cannot serve another model turn yet."""


class BenchmarkAuthenticationError(RuntimeError):
    """The benchmark cannot continue without renewed ChatGPT authentication."""


def _find_subscription_usage_limit(state: Any) -> str | None:
    for event in reversed(getattr(state, 'history', []) or []):
        if getattr(event, 'error_category', None) == _QUOTA_ERROR_CATEGORY:
            return str(
                getattr(event, 'content', '') or 'Subscription usage limit reached'
            )
    return None


def _find_authentication_error(state: Any) -> str | None:
    for event in reversed(getattr(state, 'history', []) or []):
        if getattr(event, 'error_category', None) == _AUTH_ERROR_CATEGORY:
            return str(
                getattr(event, 'content', '') or 'ChatGPT authentication required'
            )
    return None


def _benchmark_user_response(state: Any) -> str:
    """Continue autonomous work, except when subscription capacity is exhausted."""
    if _find_subscription_usage_limit(state) or _find_authentication_error(state):
        return '/exit'
    from backend.app.main import auto_continue_response

    return auto_continue_response(state)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Run Grinta once in a prepared DeepSWE/Pier task workspace.'
    )
    parser.add_argument('--workspace', required=True, help='Prepared task repository')
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument('--instruction-file', help='UTF-8 task instruction file')
    task.add_argument('--instruction', help='Task instruction text')
    task.add_argument(
        '--shared-task', help='Shared DeepSWE task.json (model-free preflight only)'
    )
    parser.add_argument(
        '--model',
        default='codex/gpt-5.6-sol',
        help='Exact provider/model identifier recorded and used for this run',
    )
    parser.add_argument(
        '--reasoning-effort',
        default='xhigh',
        choices=('low', 'medium', 'high', 'xhigh', 'max'),
        help='Frozen reasoning effort (default: xhigh)',
    )
    parser.add_argument('--task-id', required=True, help='DeepSWE task identifier')
    parser.add_argument(
        '--grinta-commit',
        required=True,
        help='Exact Grinta Git commit used to build/install the benchmark agent',
    )
    parser.add_argument(
        '--output-dir', required=True, help='Directory for patch, trace, and manifest'
    )
    parser.add_argument(
        '--config', default=str(_DEFAULT_CONFIG), help='Frozen benchmark overlay JSON'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate and print the resolved protocol',
    )
    return parser


def _run_git(
    workspace: Path,
    *args: str,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> str:
    completed = subprocess.run(
        ['git', *args],
        cwd=workspace,
        env=env,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f'git {" ".join(args)} failed: {detail}')
    return completed.stdout


def _git_identity(repo: Path) -> str:
    return _run_git(repo, 'rev-parse', 'HEAD').strip()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _capture_patch(
    workspace: Path, baseline_commit: str, *, comparison_edit_profile: str | None = None
) -> str:
    """Capture tracked, untracked, staged, and agent-committed changes.

    A temporary index gives Git a view of the final worktree without changing the
    task repository's real index. Comparing that index to the initial commit also
    includes changes if the agent created commits during its run.
    """
    if comparison_edit_profile == 'agentless-ml-v1':
        from backend.execution.comparison_edit_guard import ComparisonEditGuard

        ComparisonEditGuard(workspace, baseline_commit).check()
    with tempfile.TemporaryDirectory(prefix='grinta-benchmark-index-') as tmp:
        index_path = Path(tmp) / 'index'
        env = dict(os.environ)
        env['GIT_INDEX_FILE'] = str(index_path)
        _run_git(workspace, 'read-tree', baseline_commit, env=env)
        _run_git(workspace, 'add', '-A', '--', '.', env=env)
        return _run_git(
            workspace,
            'diff',
            '--cached',
            '--binary',
            '--no-ext-diff',
            baseline_commit,
            env=env,
        )


def _materialize_submission_head(
    workspace: Path, baseline_commit: str, patch: str
) -> dict[str, Any]:
    """Make an uncommitted benchmark result visible to a ``HEAD`` collector.

    DeepSWE's task hook collects ``baseline..HEAD`` even though coding harnesses
    naturally produce a final filesystem state.  If the agent already created a
    commit, it remains authoritative.  Otherwise, create a synthetic commit from
    the exact patch captured with a temporary index.  This runs only inside the
    disposable benchmark workspace; normal Grinta sessions never commit files.
    """
    committed_patch = _run_git(
        workspace,
        'diff',
        '--binary',
        '--no-ext-diff',
        baseline_commit,
        'HEAD',
    )
    if committed_patch.strip():
        return {
            'mode': 'agent_commit',
            'head': _git_identity(workspace),
            'synthetic_commit': False,
        }
    if not patch.strip():
        return {
            'mode': 'no_changes',
            'head': _git_identity(workspace),
            'synthetic_commit': False,
        }

    with tempfile.TemporaryDirectory(prefix='grinta-submission-index-') as tmp:
        index_path = Path(tmp) / 'index'
        env = dict(os.environ)
        env.update(
            {
                'GIT_INDEX_FILE': str(index_path),
                'GIT_AUTHOR_NAME': 'Grinta Benchmark Packager',
                'GIT_AUTHOR_EMAIL': 'grinta-benchmark@localhost',
                'GIT_COMMITTER_NAME': 'Grinta Benchmark Packager',
                'GIT_COMMITTER_EMAIL': 'grinta-benchmark@localhost',
            }
        )
        _run_git(workspace, 'read-tree', baseline_commit, env=env)
        # Populate the synthetic tree from the same final worktree used by
        # _capture_patch.  This avoids platform-specific ``git apply --cached``
        # index/worktree consistency checks (notably with Windows line endings).
        _run_git(workspace, 'add', '-A', '--', '.', env=env)
        tree = _run_git(workspace, 'write-tree', env=env).strip()
        commit = _run_git(
            workspace,
            'commit-tree',
            tree,
            '-p',
            baseline_commit,
            '-m',
            'package Grinta benchmark submission',
            env=env,
        ).strip()

    _run_git(workspace, 'update-ref', 'HEAD', commit)
    materialized = _run_git(
        workspace,
        'diff',
        '--binary',
        '--no-ext-diff',
        baseline_commit,
        'HEAD',
    )
    if materialized != patch:
        raise RuntimeError('Synthetic submission commit does not match captured patch')
    return {
        'mode': 'synthetic_commit',
        'head': commit,
        'synthetic_commit': True,
    }


def _load_instruction(args: argparse.Namespace) -> str:
    if args.instruction_file:
        value = Path(args.instruction_file).read_text(encoding='utf-8')
    else:
        value = str(args.instruction)
    value = value.strip()
    if not value:
        raise ValueError('task instruction must not be empty')
    return value


def _extract_metrics(state: Any) -> dict[str, Any]:
    if state is None:
        return {'agent_state': None, 'turn_count': None, 'cost_usd': None}
    turns = getattr(getattr(state, 'iteration_flag', None), 'current_value', None)
    stats = getattr(state, 'conversation_stats', None)
    metrics = stats.get_combined_metrics() if stats is not None else None
    cost = getattr(metrics, 'accumulated_cost', None) if metrics is not None else None
    terminal_state = getattr(state, 'agent_state', None)
    return {
        'agent_state': str(terminal_state) if terminal_state is not None else None,
        'turn_count': turns,
        'cost_usd': cost,
    }


def _validate_subscription_model(model: str) -> None:
    if not model.startswith(_SUBSCRIPTION_MODEL_PREFIX):
        raise ValueError(
            'This protocol is subscription-only: model must use the codex/ transport, '
            'not a usage-billed API provider.'
        )


def _load_config(
    config_path: Path,
    workspace: Path,
    trajectory_path: Path,
    model: str,
    reasoning_effort: str,
):
    from backend.core.config.config_loader import (
        finalize_config,
        load_app_config,
        load_from_json,
    )

    config = load_app_config(set_logging_levels=False)
    load_from_json(config, str(config_path))
    config.project_root = str(workspace)
    config.save_trajectory_path = str(trajectory_path)
    config.save_screenshots_in_trajectory = False
    llm = config.get_llm_config()
    llm.model = model
    llm.reasoning_effort = reasoning_effort
    # Catalog prices are useful for comparison but are not the user's actual
    # subscription charge. Never stop a Plus-backed run on a synthetic USD cap.
    config.max_budget_per_task = None
    finalize_config(config)
    return config


async def _run(config: Any, instruction: str) -> Any:
    from backend.app.main import run_controller
    from backend.ledger.action import MessageAction

    return await run_controller(
        config_=config,
        initial_action=MessageAction(content=instruction),
        headless_mode=True,
        fake_user_response_fn=_benchmark_user_response,
    )


def _manifest_base(
    *,
    args: argparse.Namespace,
    workspace: Path,
    config_path: Path,
    instruction: str,
    baseline_commit: str,
) -> dict[str, Any]:
    return {
        'schema_version': 1,
        'benchmark': 'DeepSWE v1.1',
        'task_id': args.task_id,
        'model': args.model,
        'reasoning_effort': args.reasoning_effort,
        'authentication': 'chatgpt_subscription',
        'usage_billed_api': False,
        'cost_semantics': 'api_equivalent_estimate_not_actual_subscription_charge',
        'workspace': str(workspace),
        'task_baseline_commit': baseline_commit,
        'grinta_commit': args.grinta_commit,
        'config_path': str(config_path),
        'config_sha256': _sha256_bytes(config_path.read_bytes()),
        'instruction_sha256': _sha256_bytes(instruction.encode('utf-8')),
        'human_intervention': 0,
        'verdict': None,
        'verdict_source': 'external_deepswe_verifier',
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = Path(args.workspace).resolve()
    config_path = Path(args.config).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not workspace.is_dir():
        raise SystemExit(f'Workspace does not exist: {workspace}')
    if args.shared_task:
        from evaluation.deepswe.shared_task import load_shared_task, preflight_manifest

        record = load_shared_task(args.shared_task)
        if args.task_id != record['identity']['task_id']:
            raise SystemExit('Task ID disagrees with shared record')
        if not args.dry_run:
            raise SystemExit(
                'Shared comparison live execution is deferred: model/access, budgets '
                'and observed container matching are not configured. Use --dry-run.'
            )
        manifest = preflight_manifest(record, workspace, 'grinta', args.grinta_commit)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    if not config_path.is_file():
        raise SystemExit(f'Benchmark config does not exist: {config_path}')
    try:
        _validate_subscription_model(args.model)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    instruction = _load_instruction(args)
    baseline_commit = _git_identity(workspace)
    manifest = _manifest_base(
        args=args,
        workspace=workspace,
        config_path=config_path,
        instruction=instruction,
        baseline_commit=baseline_commit,
    )
    if args.dry_run:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = output_dir / 'trajectory.json'
    patch_path = output_dir / 'model.patch'
    manifest_path = output_dir / 'manifest.json'
    started = time.monotonic()
    run_started_at = datetime.now(UTC).isoformat()

    try:
        config = _load_config(
            config_path,
            workspace,
            trajectory_path,
            args.model,
            args.reasoning_effort,
        )
        state = asyncio.run(_run(config, instruction))
        usage_limit = _find_subscription_usage_limit(state)
        if usage_limit:
            raise SubscriptionUsageLimitError(usage_limit)
        auth_error = _find_authentication_error(state)
        if auth_error:
            raise BenchmarkAuthenticationError(auth_error)
        metrics = _extract_metrics(state)
        patch = _capture_patch(
            workspace,
            baseline_commit,
            comparison_edit_profile=getattr(
                config.security, 'comparison_edit_profile', None
            ),
        )
        patch_path.write_text(patch, encoding='utf-8')
        submission_packaging = _materialize_submission_head(
            workspace, baseline_commit, patch
        )
        manifest.update(
            {
                'run_status': 'completed',
                'run_started_at': run_started_at,
                'duration_seconds': round(time.monotonic() - started, 3),
                'agent': metrics,
                'patch_path': str(patch_path),
                'patch_sha256': _sha256_bytes(patch.encode('utf-8')),
                'trajectory_path': str(trajectory_path),
                'submission_packaging': submission_packaging,
            }
        )
    except Exception as exc:
        if isinstance(exc, SubscriptionUsageLimitError):
            run_status = 'capacity_error'
        elif isinstance(exc, BenchmarkAuthenticationError):
            run_status = 'authentication_error'
        else:
            run_status = 'harness_error'
        manifest.update(
            {
                'run_status': run_status,
                'run_started_at': run_started_at,
                'duration_seconds': round(time.monotonic() - started, 3),
                'error_type': type(exc).__name__,
                'error': str(exc),
            }
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8'
        )
        print(f'Grinta benchmark run failed; see {manifest_path}', file=sys.stderr)
        return 1

    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8'
    )
    print(f'Run completed; external verification required: {manifest_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
