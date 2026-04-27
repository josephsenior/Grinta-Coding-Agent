from __future__ import annotations

from pathlib import Path

import pytest

from backend.evaluation.agent_eval_pack import (
    EvalPackError,
    build_results_template,
    compare_agents,
    load_eval_pack,
    render_markdown_summary,
    score_agent_results,
)


def _sample_pack() -> dict:
    return {
        'pack_id': 'sample_pack',
        'version': '1',
        'agents': [{'id': 'grinta'}],
        'metric_weights': {
            'success': 45,
            'verification_score': 20,
            'instruction_adherence_score': 10,
            'tool_discipline_score': 10,
            'code_quality_score': 10,
            'recovery_score': 5,
        },
        'tasks': [
            {
                'id': 'bugfix',
                'title': 'Bugfix',
                'category': 'bugfix',
                'recovery_required': False,
                'budgets': {'turns': 10, 'latency_seconds': 100.0, 'cost_usd': 1.0},
            },
            {
                'id': 'recovery',
                'title': 'Recovery',
                'category': 'recovery',
                'recovery_required': True,
                'budgets': {'turns': 10, 'latency_seconds': 100.0, 'cost_usd': 1.0},
            },
        ],
    }


def _sample_results() -> dict:
    return {
        'agent_id': 'grinta',
        'pack_id': 'sample_pack',
        'pack_version': '1',
        'runs': [
            {
                'task_id': 'bugfix',
                'success': True,
                'verification_score': 5,
                'instruction_adherence_score': 4,
                'tool_discipline_score': 4,
                'code_quality_score': 5,
                'recovery_score': None,
                'turn_count': 8,
                'latency_seconds': 90.0,
                'cost_usd': 0.8,
            },
            {
                'task_id': 'recovery',
                'success': True,
                'verification_score': 4,
                'instruction_adherence_score': 4,
                'tool_discipline_score': 5,
                'code_quality_score': 4,
                'recovery_score': 5,
                'turn_count': 9,
                'latency_seconds': 95.0,
                'cost_usd': 0.9,
            },
        ],
    }


def test_load_eval_pack_validates_real_pack() -> None:
    pack_path = (
        Path(__file__).resolve().parents[4]
        / 'scripts'
        / 'evals'
        / 'agent_comparison_pack.json'
    )
    pack = load_eval_pack(pack_path)
    assert pack['pack_id'] == 'top_tier_agent_comparison'
    assert len(pack['tasks']) >= 5


def test_build_results_template_matches_task_count() -> None:
    pack = _sample_pack()
    template = build_results_template(pack, 'grinta')
    assert template['agent_id'] == 'grinta'
    assert len(template['runs']) == len(pack['tasks'])
    assert template['runs'][0]['verification_score'] is None


def test_score_agent_results_happy_path() -> None:
    scored = score_agent_results(_sample_pack(), _sample_results())
    assert scored['agent_id'] == 'grinta'
    assert scored['overall_score'] > 80
    assert scored['success_rate'] == 100.0
    assert scored['category_summary']['bugfix'] > 80


def test_recovery_metric_is_ignored_when_not_applicable() -> None:
    pack = _sample_pack()
    results = _sample_results()
    results['runs'][0]['recovery_score'] = 0
    scored = score_agent_results(pack, results)
    bugfix_task = next(task for task in scored['tasks'] if task['task_id'] == 'bugfix')
    assert 'recovery_score' not in bugfix_task['metric_detail']


def test_budget_penalty_reduces_score() -> None:
    pack = _sample_pack()
    results = _sample_results()
    results['runs'][0]['turn_count'] = 30
    scored = score_agent_results(pack, results)
    bugfix_task = next(task for task in scored['tasks'] if task['task_id'] == 'bugfix')
    assert bugfix_task['final_score'] < bugfix_task['base_score']
    assert 'turn_count' in bugfix_task['budget_penalties']


def test_missing_task_run_raises() -> None:
    pack = _sample_pack()
    results = _sample_results()
    results['runs'].pop()
    with pytest.raises(EvalPackError, match='missing task runs'):
        score_agent_results(pack, results)


def test_compare_agents_and_render_markdown() -> None:
    pack = _sample_pack()
    grinta = _sample_results()
    aider = _sample_results()
    aider['agent_id'] = 'aider'
    aider['runs'][0]['success'] = False
    comparison = compare_agents(pack, [grinta, aider])
    assert comparison[0]['agent_id'] == 'grinta'
    markdown = render_markdown_summary(comparison)
    assert '| Agent | Overall | Success Rate |' in markdown
    assert 'grinta' in markdown
    assert 'aider' in markdown
