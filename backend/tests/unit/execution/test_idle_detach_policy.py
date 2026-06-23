"""Tests for idle-output detach timeout scaling."""

from __future__ import annotations

from backend.execution.runtime_mixins.command_timeout import SAFETY_NET_TIMEOUT
from backend.execution.utils.shell.idle_detach_policy import compute_idle_detach_timeouts


def test_default_safety_net_scales_idle_to_ninety_seconds():
    hard, idle, initial = compute_idle_detach_timeouts(SAFETY_NET_TIMEOUT)
    assert hard == float(SAFETY_NET_TIMEOUT)
    assert idle == 90.0
    assert initial == 180.0


def test_explicit_timeout_scales_idle_to_half_budget():
    hard, idle, initial = compute_idle_detach_timeouts(120)
    assert hard == 120.0
    assert idle == 60.0
    assert initial == 108.0


def test_short_explicit_timeout_keeps_minimum_base_idle():
    hard, idle, initial = compute_idle_detach_timeouts(45)
    assert hard == 45.0
    assert idle == 30.0
    assert initial == 40.5


def test_blocking_doubles_idle_within_hard_limit():
    hard, idle, _initial = compute_idle_detach_timeouts(120, blocking=True)
    assert hard == 120.0
    assert idle == 108.0
