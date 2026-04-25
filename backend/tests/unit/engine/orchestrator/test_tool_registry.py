"""Tests for backend.engine.tool_registry."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.engine.function_calling import _create_tool_dispatch_map
from backend.engine.planner import OrchestratorPlanner
from backend.engine.tool_registry import validate_internal_toolset


def _make_config(**kwargs):
    cfg = MagicMock()
    # Enable most tools by default so the toolset is representative.
    cfg.enable_think = True
    cfg.enable_finish = True
    cfg.enable_editor = True
    cfg.enable_run_tests = True
    cfg.enable_apply_patch = True
    cfg.enable_internal_task_tracker = True
    cfg.enable_checkpoints = True
    cfg.enable_session_diff = True
    cfg.enable_working_memory = True
    cfg.enable_verify_file_lines = True
    cfg.enable_browsing = True
    cfg.mcp.servers = []

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


# ---------------------------------------------------------------------------
# Feature-flag combination tests
# ---------------------------------------------------------------------------


def _tool_names(tools: list) -> set[str]:
    return {t.get("function", {}).get("name") for t in tools} - {None}


def _build_toolset(**cfg_overrides) -> set[str]:
    planner = OrchestratorPlanner(
        config=_make_config(**cfg_overrides),
        llm=_make_llm(),
        safety_manager=_make_safety(),
    )
    return _tool_names(planner.build_toolset())


class TestFeatureFlagToolPresence:
    """When a feature flag is toggled, the expected tool must appear/disappear in the toolset
    and any present tool must have a corresponding dispatch handler.
    """

    def _assert_dispatch_covered(self, names: set[str]) -> None:
        dispatch = _create_tool_dispatch_map()
        missing = sorted(names - set(dispatch.keys()))
        assert missing == [], f"Tools with no dispatch handler: {missing}"

    def test_think_enabled(self):
        names = _build_toolset(enable_think=True)
        assert "think" in names
        self._assert_dispatch_covered(names)

    def test_think_disabled(self):
        names = _build_toolset(enable_think=False)
        assert "think" not in names

    def test_finish_enabled(self):
        names = _build_toolset(enable_finish=True)
        assert "finish" in names
        self._assert_dispatch_covered(names)

    def test_finish_disabled(self):
        names = _build_toolset(enable_finish=False)
        assert "finish" not in names

    def test_terminal_enabled(self):
        names = _build_toolset(enable_terminal=True)
        assert "terminal_manager" in names
        self._assert_dispatch_covered(names)

    def test_terminal_disabled(self):
        names = _build_toolset(enable_terminal=False)
        assert "terminal_manager" not in names

    def test_editor_enabled(self):
        names = _build_toolset(enable_editor=True)
        assert "str_replace_editor" in names
        self._assert_dispatch_covered(names)

    def test_editor_disabled(self):
        names = _build_toolset(enable_editor=False)
        assert "str_replace_editor" not in names

    def test_checkpoints_enabled(self):
        names = _build_toolset(enable_checkpoints=True)
        assert "checkpoint" in names
        self._assert_dispatch_covered(names)

    def test_checkpoints_disabled(self):
        names = _build_toolset(enable_checkpoints=False)
        assert "checkpoint" not in names

    def test_mcp_enabled(self):
        names = _build_toolset(enable_mcp=True)
        assert "call_mcp_tool" in names
        self._assert_dispatch_covered(names)

    def test_mcp_disabled(self):
        names = _build_toolset(enable_mcp=False)
        assert "call_mcp_tool" not in names

    def test_meta_cognition_enabled(self):
        names = _build_toolset(enable_meta_cognition=True)
        assert "communicate_with_user" in names
        self._assert_dispatch_covered(names)

    def test_meta_cognition_disabled(self):
        names = _build_toolset(enable_meta_cognition=False)
        assert "communicate_with_user" not in names

    def test_task_tracker_enabled(self):
        names = _build_toolset(enable_internal_task_tracker=True)
        assert "task_tracker" in names
        self._assert_dispatch_covered(names)

    def test_task_tracker_disabled(self):
        names = _build_toolset(enable_internal_task_tracker=False)
        assert "task_tracker" not in names

    def test_condensation_request_enabled(self):
        names = _build_toolset(enable_condensation_request=True)
        assert "summarize_context" in names
        self._assert_dispatch_covered(names)

    def test_condensation_request_disabled(self):
        names = _build_toolset(enable_condensation_request=False)
        assert "summarize_context" not in names

    def test_working_memory_enabled(self):
        names = _build_toolset(enable_working_memory=True)
        assert "memory_manager" in names
        self._assert_dispatch_covered(names)

    def test_working_memory_disabled(self):
        names = _build_toolset(enable_working_memory=False)
        assert "memory_manager" not in names

    def test_swarming_enabled(self):
        names = _build_toolset(enable_swarming=True)
        assert "delegate_task" in names
        self._assert_dispatch_covered(names)

    def test_swarming_disabled(self):
        names = _build_toolset(enable_swarming=False)
        assert "delegate_task" not in names

    def test_lsp_query_enabled_with_pylsp(self):
        from unittest.mock import patch

        with patch("backend.utils.lsp_client._detect_pylsp", return_value=True):
            names = _build_toolset(enable_lsp_query=True)
        assert "code_intelligence" in names
        self._assert_dispatch_covered(names)

    def test_lsp_query_absent_without_pylsp(self):
        from unittest.mock import patch

        with patch("backend.utils.lsp_client._detect_pylsp", return_value=False):
            names = _build_toolset(enable_lsp_query=True)
        assert "code_intelligence" not in names

    def test_all_flags_off_still_has_dispatch_coverage(self):
        """Minimal toolset (most features disabled) must still be dispatch-covered."""
        names = _build_toolset(
            enable_think=False,
            enable_finish=False,
            enable_terminal=False,
            enable_editor=False,
            enable_checkpoints=False,
            enable_mcp=False,
            enable_meta_cognition=False,
            enable_internal_task_tracker=False,
            enable_condensation_request=False,
            enable_working_memory=False,
            enable_swarming=False,
            enable_lsp_query=False,
            enable_browsing=False,
        )
        self._assert_dispatch_covered(names)

    def test_full_toolset_has_dispatch_coverage(self):
        """All-flags-on toolset must have 100 % dispatch coverage."""
        from unittest.mock import patch

        with patch("backend.utils.lsp_client._detect_pylsp", return_value=True):
            names = _build_toolset(
                enable_think=True,
                enable_finish=True,
                enable_terminal=True,
                enable_editor=True,
                enable_checkpoints=True,
                enable_mcp=True,
                enable_meta_cognition=True,
                enable_internal_task_tracker=True,
                enable_condensation_request=True,
                enable_working_memory=True,
                enable_swarming=True,
                enable_lsp_query=True,
            )
        self._assert_dispatch_covered(names)
