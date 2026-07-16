"""Tests for backend.engine.tool_registry."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.engine.function_calling.dispatch import _create_tool_dispatch_map
from backend.engine.planner import OrchestratorPlanner
from backend.engine.tool_registry import validate_internal_toolset


def _make_config(**kwargs):
    cfg = MagicMock()
    cfg.enable_editor = True
    cfg.enable_task_tracker_tool = True
    cfg.enable_checkpoints = True
    cfg.enable_working_memory = True
    cfg.enable_browsing = True
    cfg.enable_web = True
    cfg.enable_debugger = True
    cfg.mode = 'agent'
    cfg.mcp.servers = []

    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _make_llm(model: str = 'gpt-4-turbo') -> MagicMock:
    llm = MagicMock()
    llm.config.model = model
    return llm


def _make_safety() -> MagicMock:
    safety = MagicMock()
    safety.should_enforce_tools.return_value = 'required'
    return safety


def test_planner_toolset_has_dispatch_handlers():
    planner = OrchestratorPlanner(
        config=_make_config(),
        llm=_make_llm(),
        safety_manager=_make_safety(),
    )

    tools = planner.build_toolset()
    dispatch = _create_tool_dispatch_map()

    exposed_names = {t.get('function', {}).get('name') for t in tools}
    exposed_names.discard(None)

    missing = sorted(set(exposed_names) - set(dispatch.keys()))
    assert missing == []


def test_validate_internal_toolset_raises_on_mismatch():
    fake_tools = [
        {'type': 'function', 'function': {'name': 'definitely_not_a_real_tool'}}
    ]

    try:
        validate_internal_toolset(fake_tools, strict=True)
    except RuntimeError as exc:
        assert 'definitely_not_a_real_tool' in str(exc)
    else:
        raise AssertionError('Expected validate_internal_toolset to raise')


# ---------------------------------------------------------------------------
# Feature-flag combination tests
# ---------------------------------------------------------------------------


def _tool_names(tools: list) -> set[str]:
    return {t.get('function', {}).get('name') for t in tools} - {None}


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
        assert missing == [], f'Tools with no dispatch handler: {missing}'

    def test_terminal_enabled(self):
        names = _build_toolset(enable_terminal=True)
        assert {'terminal'} & names
        assert 'terminal' in names
        self._assert_dispatch_covered(names)

    def test_terminal_disabled(self):
        names = _build_toolset(enable_terminal=False)
        assert 'terminal' not in names

    def test_debugger_enabled(self):
        names = _build_toolset(enable_debugger=True)
        assert 'debugger' in names
        self._assert_dispatch_covered(names)

    def test_debugger_absent_without_supported_adapter(self):
        from unittest.mock import patch

        with patch(
            'backend.utils.runtime_detect.has_any_debug_adapter',
            return_value=False,
        ):
            names = _build_toolset(enable_debugger=True)
        assert 'debugger' not in names

    def test_debugger_disabled(self):
        names = _build_toolset(enable_debugger=False)
        assert 'debugger' not in names

    def test_editor_enabled(self):
        names = _build_toolset(enable_editor=True)
        public_file_tools = {
            'read_file',
            'find_symbols',
            'create_file',
            'replace_string',
            'multiedit',
        }
        assert public_file_tools <= names
        assert {
            'patch',
            'replace_range',
            'section_edit',
            'raw_write',
            'overwrite_file',
            'read_range',
            'replace_symbol',
            'append_text',
            'file_editor',
            'text_editor',
            'symbol_editor',
        }.isdisjoint(names)
        self._assert_dispatch_covered(names)

    def test_editor_disabled(self):
        names = _build_toolset(enable_editor=False)
        assert 'create_file' not in names
        assert 'replace_string' not in names
        assert 'multiedit' not in names

    def test_checkpoints_enabled(self):
        names = _build_toolset(enable_checkpoints=True)
        assert 'checkpoint' in names
        self._assert_dispatch_covered(names)

    def test_checkpoints_disabled(self):
        names = _build_toolset(enable_checkpoints=False)
        assert 'checkpoint' not in names

    def test_mcp_enabled(self):
        names = _build_toolset(enable_mcp=True)
        assert 'call_mcp_tool' in names
        self._assert_dispatch_covered(names)

    def test_mcp_disabled(self):
        names = _build_toolset(enable_mcp=False)
        assert 'call_mcp_tool' not in names

    def test_ask_user_always_in_toolset(self):
        names = _build_toolset()
        assert 'ask_user' in names
        self._assert_dispatch_covered(names)

    def test_task_tracker_enabled(self):
        names = _build_toolset(enable_task_tracker_tool=True)
        assert 'task_state' in names
        self._assert_dispatch_covered(names)

    def test_task_tracker_disabled(self):
        names = _build_toolset(enable_task_tracker_tool=False)
        assert 'task_state' not in names

    def test_working_memory_enabled(self):
        from unittest.mock import patch

        with patch(
            'backend.utils.optional_extras.semantic_recall_active', return_value=True
        ):
            names = _build_toolset(enable_working_memory=True)
        assert 'search_history' in names
        assert 'memory' not in names
        assert 'note' not in names
        assert 'recall' not in names
        self._assert_dispatch_covered(names)

    def test_working_memory_disabled(self):
        from unittest.mock import patch

        with patch(
            'backend.utils.optional_extras.semantic_recall_active', return_value=True
        ):
            names = _build_toolset(enable_working_memory=False)
        assert 'search_history' not in names
        assert 'memory' not in names
        assert 'note' not in names
        assert 'recall' not in names

    def test_swarming_enabled(self):
        names = _build_toolset(enable_swarming=True)
        assert 'delegate_task' not in names
        self._assert_dispatch_covered(names)

    def test_swarming_disabled(self):
        names = _build_toolset(enable_swarming=False)
        assert 'delegate_task' not in names

    def test_lsp_query_enabled_with_pylsp(self):
        from unittest.mock import patch

        with patch(
            'backend.utils.runtime_detect.detect_lsp_servers',
            return_value={'pylsp': SimpleNamespace(available=True)},
        ):
            names = _build_toolset(enable_lsp_query=True)
        assert 'lsp' in names
        self._assert_dispatch_covered(names)

    def test_lsp_query_absent_without_pylsp(self):
        from unittest.mock import patch

        with patch(
            'backend.utils.runtime_detect.detect_lsp_servers',
            return_value={},
        ):
            names = _build_toolset(enable_lsp_query=True)
        assert 'lsp' not in names

    def test_all_flags_off_still_has_dispatch_coverage(self):
        """Minimal toolset (most features disabled) must still be dispatch-covered."""
        names = _build_toolset(
            enable_terminal=False,
            enable_editor=False,
            enable_checkpoints=False,
            enable_mcp=False,
            enable_task_tracker_tool=False,
            enable_working_memory=False,
            enable_swarming=False,
            enable_lsp_query=False,
            enable_browsing=False,
            enable_debugger=False,
        )
        self._assert_dispatch_covered(names)

    def test_full_toolset_has_dispatch_coverage(self):
        """All-flags-on toolset must have 100 % dispatch coverage."""
        from unittest.mock import patch

        with patch(
            'backend.utils.runtime_detect.detect_lsp_servers',
            return_value={'pylsp': SimpleNamespace(available=True)},
        ):
            names = _build_toolset(
                enable_terminal=True,
                enable_editor=True,
                enable_checkpoints=True,
                enable_mcp=True,
                enable_task_tracker_tool=True,
                enable_working_memory=True,
                enable_swarming=True,
                enable_lsp_query=True,
                enable_debugger=True,
            )
        self._assert_dispatch_covered(names)


class TestModeToolVisibility:
    def test_plan_mode_exposes_read_only_planning_tools(self):
        from unittest.mock import patch

        with patch(
            'backend.utils.runtime_detect.detect_lsp_servers',
            return_value={'pylsp': SimpleNamespace(available=True)},
        ):
            names = _build_toolset(
                mode='plan',
                enable_terminal=True,
                enable_editor=True,
                enable_task_tracker_tool=True,
                enable_mcp=True,
                enable_browsing=True,
                enable_debugger=True,
                enable_checkpoints=True,
                enable_working_memory=True,
            )

        assert names == {
            'read_file',
            'find_symbols',
            'grep',
            'glob',
            'analyze_project_structure',
            'lsp',
            'web_search',
            'web_fetch',
            'docs_resolve',
            'docs_query',
            'ask_user',
            'task_state',
        }
        assert {
            'create_file',
            'replace_string',
            'multiedit',
            'terminal',
            'debugger',
            'call_mcp_tool',
            'browser_tool',
            'checkpoint',
            'finish',
            'communicate_with_user',
            'memory',
            'delegate_task',
            'blackboard',
        }.isdisjoint(names)

    def test_agent_mode_still_exposes_execution_tools(self):
        names = _build_toolset(
            mode='agent',
            enable_terminal=True,
            enable_editor=True,
            enable_checkpoints=False,
            enable_working_memory=False,
            enable_debugger=False,
        )
        assert {'create_file', 'replace_string', 'multiedit'} <= names
        assert {'terminal'} & names
        assert 'ask_user' in names
        assert 'terminal' in names
        assert 'call_mcp_tool' in names
        assert {
            'communicate_with_user',
            'finish',
            'debugger',
            'checkpoint',
            'memory',
            'delegate_task',
            'blackboard',
        }.isdisjoint(names)

    def test_chat_mode_exposes_discovery_and_ask_user_only(self):
        from unittest.mock import patch

        with patch(
            'backend.utils.runtime_detect.detect_lsp_servers',
            return_value={'pylsp': SimpleNamespace(available=True)},
        ):
            names = _build_toolset(
                mode='chat',
                enable_terminal=True,
                enable_editor=True,
                enable_task_tracker_tool=True,
                enable_mcp=True,
                enable_browsing=True,
                enable_debugger=True,
                enable_checkpoints=True,
                enable_working_memory=True,
            )

        assert names == {
            'read_file',
            'find_symbols',
            'grep',
            'glob',
            'analyze_project_structure',
            'lsp',
            'web_search',
            'web_fetch',
            'docs_resolve',
            'docs_query',
            'ask_user',
        }
        assert {
            'task_state',
            'create_file',
            'replace_string',
            'multiedit',
            'terminal',
            'call_mcp_tool',
        }.isdisjoint(names)
