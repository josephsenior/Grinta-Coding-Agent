"""Data-driven scoring for cross-agent coding evaluations.

The pack format is intentionally vendor-neutral: this repo can score results
from Grinta, Claude Code, Aider, OpenHands, and Copilot-style task loops
without pretending it can directly automate every external control plane.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class EvalPackError(ValueError):
    """Raised when an eval pack or results document is invalid."""


_FIVE_POINT_METRICS = (
    'verification_score',
    'instruction_adherence_score',
    'tool_discipline_score',
    'code_quality_score',
    'recovery_score',
)

_METRIC_LABELS = {
    'success': 'Success',
    'verification_score': 'Verification',
    'instruction_adherence_score': 'Adherence',
    'tool_discipline_score': 'Tool Discipline',
    'code_quality_score': 'Code Quality',
    'recovery_score': 'Recovery',
}

_BUDGET_FIELDS = {
    'turn_count': ('turns', 0.08),
    'latency_seconds': ('latency_seconds', 0.10),
    'cost_usd': ('cost_usd', 0.07),
}


def _load_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise EvalPackError(f'Expected JSON object at {path}')
    return data


def _normalize_metric(value: Any, metric_name: str) -> float:
    if not isinstance(value, (int, float)):
        raise EvalPackError(f'{metric_name} must be a number between 0 and 5')
    numeric = float(value)
    if numeric < 0 or numeric > 5:
        raise EvalPackError(f'{metric_name} must be between 0 and 5')
    return numeric / 5.0


def load_eval_pack(path: str | Path) -> dict[str, Any]:
    """Load and validate an eval pack definition."""
    pack = _load_json(path)
    required_keys = {'pack_id', 'version', 'agents', 'metric_weights', 'tasks'}
    missing = sorted(required_keys - set(pack))
    if missing:
        raise EvalPackError(f'Pack is missing required keys: {", ".join(missing)}')

    agents = pack.get('agents')
    if not isinstance(agents, list) or not agents:
        raise EvalPackError('Pack must define a non-empty agents list')
    tasks = pack.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise EvalPackError('Pack must define a non-empty tasks list')

    task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise EvalPackError('Each task entry must be an object')
        task_id = task.get('id')
        if not isinstance(task_id, str) or not task_id:
            raise EvalPackError('Each task must have a non-empty string id')
        if task_id in task_ids:
            raise EvalPackError(f'Duplicate task id: {task_id}')
        task_ids.add(task_id)

    weights = pack.get('metric_weights')
    if not isinstance(weights, dict) or 'success' not in weights:
        raise EvalPackError('Pack must define metric_weights including success')
    for metric_name in ('success', *_FIVE_POINT_METRICS):
        weight = weights.get(metric_name)
        if not isinstance(weight, (int, float)) or float(weight) <= 0:
            raise EvalPackError(
                f'metric_weights.{metric_name} must be a positive number'
            )
    return pack


def load_results_document(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate one agent's recorded results."""
    results = _load_json(path)
    required = {'agent_id', 'pack_id', 'pack_version', 'runs'}
    missing = sorted(required - set(results))
    if missing:
        raise EvalPackError(
            f'Results document is missing required keys: {", ".join(missing)}'
        )
    if not isinstance(results['runs'], list):
        raise EvalPackError('Results document runs must be a list')
    return results


def build_results_template(pack: dict[str, Any], agent_id: str) -> dict[str, Any]:
    """Build a blank results document for one agent."""
    return {
        'agent_id': agent_id,
        'pack_id': pack['pack_id'],
        'pack_version': pack['version'],
        'metadata': {
            'model': '',
            'run_date': '',
            'operator': '',
            'notes': '',
        },
        'runs': [
            {
                'task_id': task['id'],
                'success': False,
                'verification_score': None,
                'instruction_adherence_score': None,
                'tool_discipline_score': None,
                'code_quality_score': None,
                'recovery_score': None,
                'turn_count': None,
                'latency_seconds': None,
                'cost_usd': None,
                'notes': '',
                'evidence': [],
            }
            for task in pack['tasks']
        ],
    }


def _task_map(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task['id']: task for task in pack['tasks']}


def _validate_results_against_pack(
    pack: dict[str, Any],
    results: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if results.get('pack_id') != pack.get('pack_id'):
        raise EvalPackError('Results pack_id does not match eval pack')
    if results.get('pack_version') != pack.get('version'):
        raise EvalPackError('Results pack_version does not match eval pack version')

    task_map = _task_map(pack)
    seen: set[str] = set()
    run_map: dict[str, dict[str, Any]] = {}
    for run in results['runs']:
        if not isinstance(run, dict):
            raise EvalPackError('Each run entry must be an object')
        task_id = run.get('task_id')
        if not isinstance(task_id, str) or task_id not in task_map:
            raise EvalPackError(f'Unknown task id in results: {task_id!r}')
        if task_id in seen:
            raise EvalPackError(f'Duplicate run entry for task {task_id}')
        seen.add(task_id)
        run_map[task_id] = run

    missing_tasks = sorted(set(task_map) - seen)
    if missing_tasks:
        raise EvalPackError(
            f'Results document is missing task runs for: {", ".join(missing_tasks)}'
        )
    return run_map


def _base_score(
    task: dict[str, Any],
    run: dict[str, Any],
    weights: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    weighted_sum = 0.0
    total_weight = 0.0
    detail: dict[str, float] = {}

    success = bool(run.get('success', False))
    success_weight = float(weights['success'])
    success_score = 1.0 if success else 0.0
    weighted_sum += success_weight * success_score
    total_weight += success_weight
    detail['success'] = success_score * 100.0

    for metric_name in _FIVE_POINT_METRICS:
        raw = run.get(metric_name)
        if metric_name == 'recovery_score' and not bool(task.get('recovery_required')):
            continue
        if raw is None:
            continue
        normalized = _normalize_metric(raw, metric_name)
        weight = float(weights[metric_name])
        weighted_sum += weight * normalized
        total_weight += weight
        detail[metric_name] = normalized * 100.0

    if total_weight <= 0:
        raise EvalPackError(
            f'Task {task["id"]} ended up with zero active metric weight'
        )

    base = (weighted_sum / total_weight) * 100.0
    if not success:
        base = min(base, 49.0)
    return base, detail


def _budget_penalties(task: dict[str, Any], run: dict[str, Any]) -> dict[str, float]:
    budgets = task.get('budgets', {})
    if not isinstance(budgets, dict):
        return {}

    penalties: dict[str, float] = {}
    for result_field, (budget_key, max_penalty) in _BUDGET_FIELDS.items():
        actual = run.get(result_field)
        budget = budgets.get(budget_key)
        if not isinstance(actual, (int, float)) or not isinstance(budget, (int, float)):
            continue
        if budget <= 0 or actual <= budget:
            continue
        overrun_ratio = (float(actual) - float(budget)) / float(budget)
        penalties[result_field] = min(
            float(max_penalty), overrun_ratio * float(max_penalty)
        )
    return penalties


def score_agent_results(
    pack: dict[str, Any], results: dict[str, Any]
) -> dict[str, Any]:
    """Score one agent's results against the eval pack."""
    weights = pack['metric_weights']
    run_map = _validate_results_against_pack(pack, results)

    per_task: list[dict[str, Any]] = []
    aggregate_metrics: dict[str, list[float]] = {name: [] for name in _METRIC_LABELS}
    category_scores: dict[str, list[float]] = {}

    for task in pack['tasks']:
        run = run_map[task['id']]
        base_score, metric_detail = _base_score(task, run, weights)
        penalties = _budget_penalties(task, run)
        penalty_ratio = min(0.25, sum(penalties.values()))
        final_score = round(base_score * (1.0 - penalty_ratio), 2)
        category = task['category']
        category_scores.setdefault(category, []).append(final_score)

        for metric_name, value in metric_detail.items():
            aggregate_metrics.setdefault(metric_name, []).append(value)

        per_task.append(
            {
                'task_id': task['id'],
                'title': task['title'],
                'category': category,
                'success': bool(run.get('success', False)),
                'base_score': round(base_score, 2),
                'final_score': final_score,
                'metric_detail': metric_detail,
                'budget_penalties': penalties,
            }
        )

    overall_score = round(
        sum(task['final_score'] for task in per_task) / len(per_task), 2
    )
    summary_metrics = {
        _METRIC_LABELS[name]: round(sum(values) / len(values), 2)
        for name, values in aggregate_metrics.items()
        if values
    }
    category_summary = {
        category: round(sum(values) / len(values), 2)
        for category, values in category_scores.items()
    }
    success_rate = round(
        (sum(1 for task in per_task if task['success']) / len(per_task)) * 100.0,
        2,
    )

    return {
        'agent_id': results['agent_id'],
        'pack_id': pack['pack_id'],
        'pack_version': pack['version'],
        'overall_score': overall_score,
        'success_rate': success_rate,
        'summary_metrics': summary_metrics,
        'category_summary': category_summary,
        'tasks': per_task,
    }


def compare_agents(
    pack: dict[str, Any],
    results_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Score and sort multiple agents on the same pack."""
    scored = [score_agent_results(pack, document) for document in results_documents]
    return sorted(
        scored,
        key=lambda row: (row['overall_score'], row['success_rate']),
        reverse=True,
    )


def render_markdown_summary(comparison: list[dict[str, Any]]) -> str:
    """Render a compact markdown leaderboard."""
    if not comparison:
        return 'No scored agent runs.'

    lines = [
        '| Agent | Overall | Success Rate | Verification | Adherence | Tool Discipline | Code Quality | Recovery |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for row in comparison:
        metrics = row.get('summary_metrics', {})
        lines.append(
            '| {agent} | {overall:.2f} | {success:.2f}% | {verification:.2f} | {adherence:.2f} | {tool:.2f} | {code:.2f} | {recovery:.2f} |'.format(
                agent=row['agent_id'],
                overall=row['overall_score'],
                success=row['success_rate'],
                verification=metrics.get('Verification', 0.0),
                adherence=metrics.get('Adherence', 0.0),
                tool=metrics.get('Tool Discipline', 0.0),
                code=metrics.get('Code Quality', 0.0),
                recovery=metrics.get('Recovery', 0.0),
            )
        )

    lines.append('')
    lines.append('Category averages:')
    for row in comparison:
        category_bits = ', '.join(
            f'{name}={score:.2f}'
            for name, score in sorted(row.get('category_summary', {}).items())
        )
        lines.append(f'- {row["agent_id"]}: {category_bits}')
    return '\n'.join(lines)
