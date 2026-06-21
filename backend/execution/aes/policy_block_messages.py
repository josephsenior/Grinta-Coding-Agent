"""Compact user-facing policy block messages for agent observations."""

from __future__ import annotations


def hardened_local_block_message(reason_code: str) -> str:
    return f'Action blocked by hardened_local policy ({reason_code})'


def hardened_local_session_closed_message() -> str:
    return hardened_local_block_message('terminal session outside workspace')


def safety_block_message(risk: str) -> str:
    return f'Action blocked for safety (risk={risk})'
