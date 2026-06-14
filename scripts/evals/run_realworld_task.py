"""Run a single real-world eval-pack task headlessly with benchmark settings.

Loads repo ``settings.json`` first, then merges ``settings.bench.json`` overrides.
After the run, writes a manifest with measured turn count, latency, and cost so
you can fill qualitative scores into the results template and score with
``scripts/score_agent_eval_pack.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PACK = _REPO_ROOT / 'scripts' / 'evals' / 'agent_comparison_pack.json'
_BENCH_SETTINGS = _REPO_ROOT / 'settings.bench.json'
_RESULTS_ROOT = _REPO_ROOT / 'scripts' / 'evals' / 'results'


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Run one real-world eval-pack task with benchmark settings.',
    )
    parser.add_argument(
        '--pack',
        default=str(_DEFAULT_PACK),
        help='Path to the eval pack JSON file.',
    )
    parser.add_argument(
        '--task-id',
        help='Task id from the pack (use --list-tasks to inspect).',
    )
    parser.add_argument(
        '--directory',
        '-d',
        help='Working directory for the agent (open project root).',
    )
    parser.add_argument(
        '--list-tasks',
        action='store_true',
        help='List tasks in the pack and exit.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print resolved config and prompt without running the agent.',
    )
    parser.add_argument(
        '--prompt-file',
        help='Optional file whose contents replace the pack task prompt.',
    )
    parser.add_argument(
        '--results-out',
        help=(
            'Optional results JSON to update with measured run fields '
            '(turn_count, latency_seconds, cost_usd). Qualitative scores stay manual.'
        ),
    )
    parser.add_argument(
        '--agent-id',
        default='grinta',
        help='Agent id recorded in manifests and results documents.',
    )
    return parser


def _load_pack(pack_path: Path) -> dict[str, Any]:
    from backend.evaluation.agent_eval_pack import load_eval_pack

    return load_eval_pack(pack_path)


def _find_task(pack: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in pack['tasks']:
        if task['id'] == task_id:
            return task
    known = ', '.join(task['id'] for task in pack['tasks'])
    raise SystemExit(f'Unknown task id {task_id!r}. Known tasks: {known}')


def _resolve_prompt(task: dict[str, Any], prompt_file: str | None) -> str:
    if prompt_file:
        return Path(prompt_file).read_text(encoding='utf-8').strip()
    return str(task['prompt']).strip()


def _load_bench_config():
    from backend.core.config.config_loader import (
        finalize_config,
        load_app_config,
        load_from_json,
    )

    config = load_app_config(set_logging_levels=False)
    if _BENCH_SETTINGS.is_file():
        load_from_json(config, str(_BENCH_SETTINGS))
        finalize_config(config)
    return config


def _apply_task_budgets(config, task: dict[str, Any]) -> None:
    budgets = task.get('budgets') or {}
    turns = budgets.get('turns')
    cost = budgets.get('cost_usd')
    if isinstance(turns, (int, float)) and int(turns) > 0:
        config.max_iterations = int(turns)
    if isinstance(cost, (int, float)) and float(cost) > 0:
        config.max_budget_per_task = float(cost)


def _print_tasks(pack: dict[str, Any]) -> None:
    print(f"Pack: {pack['pack_id']} ({pack['version']})")
    for task in pack['tasks']:
        budgets = task.get('budgets') or {}
        print(
            f"  - {task['id']}: {task['title']} "
            f"[{task['category']}] "
            f"(turns<={budgets.get('turns', '?')}, "
            f"cost<=${budgets.get('cost_usd', '?')})"
        )


def _agent_finished_successfully(state) -> bool:
    from backend.core.schemas import AgentState

    return state is not None and state.agent_state == AgentState.FINISHED


def _extract_run_metrics(state) -> dict[str, Any]:
    if state is None:
        return {
            'turn_count': None,
            'cost_usd': None,
            'agent_state': None,
        }

    turn_count = getattr(getattr(state, 'iteration_flag', None), 'current_value', None)
    metrics = None
    conversation_stats = getattr(state, 'conversation_stats', None)
    if conversation_stats is not None:
        metrics = conversation_stats.get_combined_metrics()
    cost_usd = getattr(metrics, 'accumulated_cost', None) if metrics else None
    agent_state = getattr(state, 'agent_state', None)
    return {
        'turn_count': turn_count,
        'cost_usd': cost_usd,
        'agent_state': str(agent_state) if agent_state is not None else None,
    }


def _write_manifest(
    *,
    run_dir: Path,
    task: dict[str, Any],
    pack: dict[str, Any],
    session_id: str,
    prompt: str,
    latency_seconds: float,
    metrics: dict[str, Any],
    state,
    trajectory_path: Path | None,
    agent_id: str,
) -> Path:
    manifest = {
        'agent_id': agent_id,
        'pack_id': pack['pack_id'],
        'pack_version': pack['version'],
        'task_id': task['id'],
        'task_title': task['title'],
        'task_category': task['category'],
        'session_id': session_id,
        'run_date': datetime.now(UTC).isoformat(),
        'latency_seconds': round(latency_seconds, 2),
        'turn_count': metrics.get('turn_count'),
        'cost_usd': metrics.get('cost_usd'),
        'agent_state': metrics.get('agent_state'),
        'finished_successfully': _agent_finished_successfully(state),
        'trajectory_path': str(trajectory_path) if trajectory_path else None,
        'prompt': prompt,
        'budgets': task.get('budgets'),
        'required_evidence': task.get('required_evidence'),
        'success_criteria': task.get('success_criteria'),
    }
    manifest_path = run_dir / 'manifest.json'
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    return manifest_path


def _update_results_file(
    results_path: Path,
    *,
    pack: dict[str, Any],
    task_id: str,
    agent_id: str,
    latency_seconds: float,
    metrics: dict[str, Any],
    notes: str,
) -> None:
    from backend.evaluation.agent_eval_pack import (
        build_results_template,
        load_results_document,
    )

    if results_path.is_file():
        results = load_results_document(results_path)
    else:
        results = build_results_template(pack, agent_id)
        results_path.parent.mkdir(parents=True, exist_ok=True)

    for run in results.get('runs', []):
        if run.get('task_id') != task_id:
            continue
        run['turn_count'] = metrics.get('turn_count')
        run['latency_seconds'] = round(latency_seconds, 2)
        run['cost_usd'] = metrics.get('cost_usd')
        if notes:
            run['notes'] = notes
        break
    else:
        raise SystemExit(f'Task {task_id!r} not found in results document {results_path}')

    metadata = results.setdefault('metadata', {})
    if not metadata.get('run_date'):
        metadata['run_date'] = datetime.now(UTC).date().isoformat()
    if not metadata.get('model'):
        from backend.core.config.config_loader import load_app_config

        cfg = load_app_config(set_logging_levels=False)
        llm = cfg.get_llm_config()
        metadata['model'] = llm.model or ''

    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )


async def _run_task(
    *,
    config,
    prompt: str,
    project_root: Path,
) -> tuple[Any, str, float]:
    from backend.core.bootstrap.main import auto_continue_response, run_controller
    from backend.ledger.action import MessageAction

    config.project_root = str(project_root.resolve())
    initial_action = MessageAction(content=prompt)

    started = time.monotonic()
    state = await run_controller(
        config_=config,
        initial_action=initial_action,
        headless_mode=True,
        fake_user_response_fn=auto_continue_response,
    )
    latency_seconds = time.monotonic() - started
    session_id = getattr(state, 'session_id', None) or 'unknown'
    return state, str(session_id), latency_seconds


def _resolve_trajectory_path(config, session_id: str) -> Path | None:
    raw = config.save_trajectory_path
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    if path.suffix == '.json':
        return path if path.is_file() else None
    candidate = path / f'{session_id}.json'
    return candidate if candidate.is_file() else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    pack_path = Path(args.pack).resolve()
    pack = _load_pack(pack_path)

    if args.list_tasks:
        _print_tasks(pack)
        return 0

    if not args.task_id:
        parser.error('--task-id is required unless --list-tasks is used.')
    if not args.directory:
        parser.error('--directory is required unless --list-tasks is used.')

    task = _find_task(pack, args.task_id)
    prompt = _resolve_prompt(task, args.prompt_file)
    project_root = Path(args.directory).resolve()
    if not project_root.is_dir():
        raise SystemExit(f'Project directory does not exist: {project_root}')

    config = _load_bench_config()
    _apply_task_budgets(config, task)

    if args.dry_run:
        llm = config.get_llm_config()
        print('Dry run - would execute with:')
        print(f'  model: {llm.model}')
        print(f'  project_root: {project_root}')
        print(f'  max_iterations: {config.max_iterations}')
        print(f'  max_budget_per_task: {config.max_budget_per_task}')
        print(f'  autonomy: {config.get_agent_config(config.default_agent).autonomy_level}')
        print(f'  task: {task["id"]} ({task["title"]})')
        print('  prompt:')
        print(prompt)
        return 0

    run_stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    run_dir = _RESULTS_ROOT / f'{run_stamp}_{task["id"]}'
    run_dir.mkdir(parents=True, exist_ok=True)

    state, session_id, latency_seconds = asyncio.run(
        _run_task(config=config, prompt=prompt, project_root=project_root)
    )
    if session_id == 'unknown' and state is not None:
        session_id = getattr(state, 'session_id', None) or session_id
    metrics = _extract_run_metrics(state)
    trajectory_path = _resolve_trajectory_path(config, session_id)

    manifest_path = _write_manifest(
        run_dir=run_dir,
        task=task,
        pack=pack,
        session_id=session_id,
        prompt=prompt,
        latency_seconds=latency_seconds,
        metrics=metrics,
        state=state,
        trajectory_path=trajectory_path,
        agent_id=args.agent_id,
    )

    if args.results_out:
        _update_results_file(
            Path(args.results_out),
            pack=pack,
            task_id=task['id'],
            agent_id=args.agent_id,
            latency_seconds=latency_seconds,
            metrics=metrics,
            notes=f'Manifest: {manifest_path}',
        )

    finished = _agent_finished_successfully(state)
    print(f'Task {task["id"]} finished: agent_state={metrics["agent_state"]}')
    print(f'  turns={metrics["turn_count"]}  cost=${metrics["cost_usd"]}  '
          f'latency={latency_seconds:.1f}s')
    print(f'  manifest: {manifest_path}')
    if trajectory_path:
        print(f'  trajectory: {trajectory_path}')
    if args.results_out:
        print(f'  results updated: {args.results_out}')
    if not finished:
        print(
            '  Note: agent did not reach FINISHED — review manifest/trajectory, '
            'then score success and qualitative metrics manually.',
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
