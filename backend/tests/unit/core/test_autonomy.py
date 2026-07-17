"""Unit tests for autonomy levels and notice formatting."""

from __future__ import annotations

import pytest

from backend.core.autonomy import (
    AutonomyLevel,
    autonomy_runtime_notice,
    normalize_autonomy_level,
    resolve_persisted_autonomy_level,
    security_risk_required_for_autonomy,
)


def test_normalize_autonomy_level_standard() -> None:
    # Standard string values
    assert normalize_autonomy_level('conservative') == 'conservative'
    assert normalize_autonomy_level('balanced') == 'balanced'
    assert normalize_autonomy_level('full') == 'full'


def test_normalize_autonomy_level_objects() -> None:
    # AutonomyLevel Enum members
    assert normalize_autonomy_level(AutonomyLevel.CONSERVATIVE) == 'conservative'
    assert normalize_autonomy_level(AutonomyLevel.BALANCED) == 'balanced'
    assert normalize_autonomy_level(AutonomyLevel.FULL) == 'full'


def test_normalize_autonomy_level_edge_cases() -> None:
    # Casing and spaces
    assert normalize_autonomy_level('  CoNsErVaTiVe  ') == 'conservative'
    assert normalize_autonomy_level('  FULL\n') == 'full'

    # Dot-separated paths (e.g. from qualified names)
    assert normalize_autonomy_level('AutonomyLevel.CONSERVATIVE') == 'conservative'
    assert normalize_autonomy_level('foo.bar.balanced') == 'balanced'

    # Invalid values are returned normalized, not matched to BALANCED
    assert normalize_autonomy_level('invalid_level') == 'invalid_level'
    assert normalize_autonomy_level('') == 'balanced'  # None / empty string resolves to BALANCED
    assert normalize_autonomy_level(None) == 'balanced'


def test_security_risk_required_for_autonomy() -> None:
    # Full autonomy does not require security risk declarations
    assert security_risk_required_for_autonomy('full') is False
    assert security_risk_required_for_autonomy(AutonomyLevel.FULL) is False

    # Conservative and balanced do require them
    assert security_risk_required_for_autonomy('conservative') is True
    assert security_risk_required_for_autonomy(AutonomyLevel.CONSERVATIVE) is True
    assert security_risk_required_for_autonomy('balanced') is True
    assert security_risk_required_for_autonomy(AutonomyLevel.BALANCED) is True

    # Fallback behavior
    assert security_risk_required_for_autonomy(None) is True
    assert security_risk_required_for_autonomy('unknown') is True


def test_resolve_persisted_autonomy_level() -> None:
    assert resolve_persisted_autonomy_level('CONSERVATIVE') == 'conservative'
    assert resolve_persisted_autonomy_level(AutonomyLevel.FULL) == 'full'
    assert resolve_persisted_autonomy_level(None) == 'balanced'


def test_autonomy_runtime_notice() -> None:
    # Conservative
    conservative_notice = autonomy_runtime_notice(AutonomyLevel.CONSERVATIVE)
    assert 'conservative' in conservative_notice
    assert 'confirmation before shell, edits, terminal, browser, MCP, and delegation' in conservative_notice
    assert 'security_risk is required' in conservative_notice

    # Balanced
    balanced_notice = autonomy_runtime_notice(AutonomyLevel.BALANCED)
    assert 'balanced' in balanced_notice
    assert 'confirmation for high-risk actions only' in balanced_notice
    assert 'security_risk is required' in balanced_notice

    # Full
    full_notice = autonomy_runtime_notice(AutonomyLevel.FULL)
    assert 'full' in full_notice
    assert 'no confirmation prompts' in full_notice
    assert 'security_risk is optional' in full_notice

    # Default / Unknown fallback (should be treated as BALANCED)
    unknown_notice = autonomy_runtime_notice('unknown')
    assert 'balanced' in unknown_notice
    assert 'confirmation for high-risk actions only' in unknown_notice
    assert 'security_risk is required' in unknown_notice
