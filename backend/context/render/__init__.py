"""Shared render helpers for task and goal context projections."""

from backend.context.render.execution_contract import (
    build_execution_contract,
    build_execution_contract_lines,
)
from backend.context.render.task_context import (
    cap_line,
    render_acceptance_gates,
    render_active_scope,
    render_goal_header,
    render_task_plan,
)

__all__ = [
    'build_execution_contract',
    'build_execution_contract_lines',
    'cap_line',
    'render_acceptance_gates',
    'render_active_scope',
    'render_goal_header',
    'render_task_plan',
]
