"""Tests for step phase breadcrumbs."""

from __future__ import annotations

from backend.core import step_phase as sp


def test_step_phase_set_get_clear():
    sp.clear_step_phase()
    assert sp.get_step_phase() == 'idle'
    sp.set_step_phase('step_inner:execute_action:edit')
    assert sp.get_step_phase() == 'step_inner:execute_action:edit'
    sp.clear_step_phase()
    assert sp.get_step_phase() == 'idle'
