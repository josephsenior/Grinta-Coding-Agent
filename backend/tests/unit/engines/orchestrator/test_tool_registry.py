"""Tests for backend.engines.orchestrator.tool_registry."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.engines.orchestrator.function_calling import _create_tool_dispatch_map
from backend.engines.orchestrator.planner import OrchestratorPlanner
from backend.engines.orchestrator.tool_registry import validate_internal_toolset


def _make_config(**kwargs):
    cfg = MagicMock()
    # Enable most tools by default so the toolset is representative.
    cfg.enable_cmd = True
    cfg.enable_think = True
    cfg.enable_finish = True
    cfg.enable_editor = True
    cfg.enable_note = True
    cfg.enable_run_tests = True
    cfg.enable_apply_patch = True
    cfg.enable_task_tracker = True
    cfg.enable_search_code = True
    cfg.enable_check_tool_status = True
    cfg.enable_workspace_status = True
    cfg.enable_error_patterns = True
    cfg.enable_checkpoints = True
    cfg.enable_project_map = True
    cfg.enable_session_diff = True
    cfg.enable_working_memory = True
    cfg.enable_verify_state = True

    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _make_llm(model: str = "gpt-4-turbo") -> MagicMock:
    llm = MagicMock()
    llm.config.model = model
    return llm


def _make_safety() -> MagicMock:
    safety = MagicMock()
    safety.should_enforce_tools.return_value = "required"
    return safety


def test_planner_toolset_has_dispatch_handlers():
    planner = OrchestratorPlanner(
        config=_make_config(),
        llm=_make_llm(),
        safety_manager=_make_safety(),
    )

    tools = planner.build_toolset()
    dispatch = _create_tool_dispatch_map()

    exposed_names = {t.get("function", {}).get("name") for t in tools}
    exposed_names.discard(None)

    missing = sorted(set(exposed_names) - set(dispatch.keys()))
    assert missing == []


def test_validate_internal_toolset_raises_on_mismatch():
    fake_tools = [
        {"type": "function", "function": {"name": "definitely_not_a_real_tool"}}
    ]

    try:
        validate_internal_toolset(fake_tools, strict=True)
    except RuntimeError as exc:
        assert "definitely_not_a_real_tool" in str(exc)
    else:
        raise AssertionError("Expected validate_internal_toolset to raise")
