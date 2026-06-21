"""Compact user-facing policy block messages for agent observations."""

from __future__ import annotations


def hardened_local_block_message(reason_code: str) -> str:
    return f'Action blocked by hardened_local policy ({reason_code})'


def hardened_local_session_closed_message() -> str:
    return hardened_local_block_message('terminal session outside workspace')


def safety_block_message(risk: str) -> str:
    return f'Action blocked for safety (risk={risk})'


def tool_result_validation_block_message(reason: str) -> str:
    detail = (reason or 'validation failed').strip()
    return f'Tool result validation blocked: {detail}'


def circuit_breaker_tripped_message() -> str:
    return 'Circuit breaker tripped'


def circuit_breaker_strategy_switch_message() -> str:
    return 'Circuit breaker: strategy switch required'


def circuit_breaker_warning_message(*, count: int, limit: int) -> str:
    return f'Circuit breaker warning ({count}/{limit})'


def agent_stall_message() -> str:
    return 'Agent loop stalled (no step progress)'


def action_timeout_message(*, timeout_seconds: float) -> str:
    seconds = max(0, int(timeout_seconds))
    return f'Action timed out after {seconds}s'


def terminal_open_loop_message() -> str:
    return 'Terminal open loop detected'


def terminal_session_not_found_message(session_id: str) -> str:
    return f"Terminal session '{session_id}' not found"


def terminal_input_rejected_message(reason_code: str) -> str:
    return f'Terminal input rejected ({reason_code})'
