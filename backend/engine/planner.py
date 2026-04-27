from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from backend.inference.catalog_loader import supports_tool_choice
from backend.inference.llm_utils import check_tools

ChatCompletionToolParam = Any

if TYPE_CHECKING:
    from backend.inference.llm import LLM
    from backend.orchestration.state.state import State

    from .safety import OrchestratorSafetyManager


# Markers that appear only in system-injected user messages (workspace context,
# playbook knowledge, knowledge-base results) — never in human-typed messages.
_INJECTED_MSG_MARKERS = (
    '<RUNTIME_INFORMATION>',
    '<REPOSITORY_INFO>',
    '<REPOSITORY_INSTRUCTIONS>',
    '<CONVERSATION_INSTRUCTIONS>',
    '<EXTRA_INFO>',
)

logger = logging.getLogger(__name__)


def _maybe_log_prompt_metrics(messages: list) -> None:
    """Log system-message character counts when APP_DEBUG_PROMPT_METRICS is set."""
    flag = os.environ.get('APP_DEBUG_PROMPT_METRICS', '').strip().lower()
    if flag not in ('1', 'true', 'yes', 'on'):
        return
    sizes: list[int] = []
    for m in messages:
        if not isinstance(m, dict) or m.get('role') != 'system':
            continue
        c = m.get('content', '')
        if isinstance(c, str):
            sizes.append(len(c))
        elif isinstance(c, list):
            sizes.append(sum(len(str(part)) for part in c))
        else:
            sizes.append(len(str(c)))
    if not sizes:
        logger.info('APP_DEBUG_PROMPT_METRICS: no system messages')
        return
    logger.info(
        'APP_DEBUG_PROMPT_METRICS: system_messages=%s chars_each=%s chars_total=%s',
        len(sizes),
        sizes,
        sum(sizes),
    )


def _get_last_user_text_from_messages(messages: list) -> str:
    """Extract text from the last user message."""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get('role') != 'user':
            continue
        content = msg.get('content', '')
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return ' '.join(
                item.get('text', '')
                for item in content
                if isinstance(item, dict) and item.get('type') == 'text'
            )
    return ''


class OrchestratorPlanner:
    """Assembles tools, messages, and LLM request payloads for Orchestrator."""

    def __init__(
        self,
        config,
        llm: LLM,
        safety_manager: OrchestratorSafetyManager,
        agent: Any = None,
    ) -> None:
        self._config = config
        self._llm = llm
        self._safety = safety_manager
        self._agent = agent
        # Lazy cache for check_tools output (model-scoped)
        self._checked_tools_cache: list[ChatCompletionToolParam] | None = None
        self._checked_tools_model: str | None = None

    # ------------------------------------------------------------------ #
    # Tool assembly
    # ------------------------------------------------------------------ #
    def build_toolset(self) -> list[ChatCompletionToolParam]:
        tools: list[ChatCompletionToolParam] = []

        self._add_core_tools(tools)
        self._add_browsing_tool(tools)
        self._add_editor_tools(tools)
        self._add_execute_mcp_tool_tool(tools)

        # Invalidate cached checked-tools when toolset is rebuilt
        self._checked_tools_cache = None
        return tools

    def _add_core_tools(self, tools: list) -> None:
        self._add_basic_tools(tools)
        self._add_edit_and_search_tools(tools)
        self._add_terminal_and_special_tools(tools)

    def _add_basic_tools(self, tools: list) -> None:
        """Add cmd, think, finish, summarize_context, memory tools."""
        from backend.engine.tools.bash import create_cmd_run_tool
        from backend.engine.tools.condensation_request import (
            create_summarize_context_tool,
        )
        from backend.engine.tools.finish import create_finish_tool
        from backend.engine.tools.memory_manager import (
            create_memory_manager_tool,
        )
        from backend.engine.tools.note import create_note_tool, create_recall_tool
        from backend.engine.tools.think import create_think_tool

        tools.append(create_cmd_run_tool())
        if getattr(self._config, 'enable_think', True):
            tools.append(create_think_tool())
        if getattr(self._config, 'enable_finish', True):
            tools.append(create_finish_tool())
        if getattr(self._config, 'enable_condensation_request', False):
            tools.append(create_summarize_context_tool())
        if getattr(self._config, 'enable_working_memory', True):
            tools.append(create_memory_manager_tool())
        tools.append(create_note_tool())
        tools.append(create_recall_tool())

    def _add_edit_and_search_tools(self, tools: list) -> None:
        """Add task_tracker, search_code, explore_code tools."""
        from backend.engine.tools.explore_code import (
            create_explore_tree_structure_tool,
            create_read_symbol_definition_tool,
        )
        from backend.engine.tools.search_code import (
            create_search_code_tool,
        )
        from backend.engine.tools.task_tracker import (
            create_task_tracker_tool,
        )

        if getattr(self._config, 'enable_internal_task_tracker', False):
            tools.append(create_task_tracker_tool())
        tools.append(create_search_code_tool())
        tools.append(create_explore_tree_structure_tool())
        tools.append(create_read_symbol_definition_tool())

    def _add_terminal_and_special_tools(self, tools: list) -> None:
        """Add terminal, optional feature tools (web search, delegate, etc.), and meta-cognition tools."""
        self._add_terminal_tools(tools)
        self._add_optional_feature_tools(tools)
        self._add_meta_cognition_tools(tools)

    def _add_terminal_tools(self, tools: list) -> None:
        """Add terminal manager tool when terminal support is enabled."""
        if getattr(self._config, 'enable_terminal', True):
            from backend.engine.tools.terminal_manager import (
                create_terminal_manager_tool,
            )

            tools.append(create_terminal_manager_tool())
        if getattr(self._config, 'enable_debugger', True):
            from backend.engine.tools.debugger import (
                create_debugger_tool,
            )

            tools.append(create_debugger_tool())

    def _add_optional_feature_tools(self, tools: list) -> None:
        """Add delegate, analyze_project_structure, etc."""
        from backend.engine.tools.analyze_project_structure import (
            create_analyze_project_structure_tool,
        )
        from backend.engine.tools.delegate_task import (
            create_delegate_task_tool,
        )
        from backend.engine.tools.lsp_query import create_lsp_query_tool

        tools.append(create_analyze_project_structure_tool())

        if getattr(self._config, 'enable_lsp_query', False):
            from backend.utils.lsp_client import _detect_pylsp

            if _detect_pylsp():
                tools.append(create_lsp_query_tool())
        if getattr(self._config, 'enable_swarming', False):
            tools.append(create_delegate_task_tool())

        from backend.engine.tools.blackboard import create_blackboard_tool

        if getattr(self._config, 'enable_blackboard', False):
            tools.append(create_blackboard_tool())

        if getattr(self._config, 'enable_checkpoints', False):
            from backend.engine.tools.checkpoint import create_checkpoint_tool

            tools.append(create_checkpoint_tool())

    def _add_lazy_import_tools(
        self, tools: list, specs: list[tuple[str, bool, str, str]]
    ) -> None:
        """Add tools from module/factory pairs when config enables them.

        specs: list of (config_key, default, module_name, factory_name).
        """
        for config_key, default, module_name, factory_name in specs:
            if getattr(self._config, config_key, default):
                mod = __import__(
                    f'backend.engine.tools.{module_name}',
                    fromlist=[factory_name],
                )
                tools.append(getattr(mod, factory_name)())

    def _add_meta_cognition_tools(self, tools: list) -> None:
        """Add uncertainty, clarification, escalate, proposal tools when meta-cognition is enabled."""
        if getattr(self._config, 'enable_meta_cognition', False):
            from backend.engine.tools.meta_cognition import (
                create_communicate_tool,
            )

            tools.append(create_communicate_tool())

    def _add_browsing_tool(self, tools: list) -> None:
        if not getattr(self._config, 'enable_browsing', False):
            return
        if getattr(self._config, 'enable_native_browser', False):
            from backend.engine.tools.browser_native import create_browser_tool

            tools.append(create_browser_tool())

    def _add_editor_tools(self, tools: list) -> None:
        if getattr(self._config, 'enable_editor', True):
            from backend.engine.tools import (
                create_text_editor_tool,
                create_symbol_editor_tool,
            )

            # Primary editor: text_editor for targeted line-level edits
            tools.append(create_text_editor_tool())
            # Advanced editor: structure_editor (tree-sitter AST) for symbol-level refactoring
            tools.append(create_symbol_editor_tool())

    def _add_execute_mcp_tool_tool(self, tools: list) -> None:
        """Add the MCP gateway proxy tool when MCP is enabled.

        The gateway replaces injecting 50+ individual MCP tool schemas.
        Available MCP tool names are listed in the system prompt instead.
        """
        if getattr(self._config, 'enable_mcp', True):
            from backend.engine.tools.execute_mcp_tool import (
                create_execute_mcp_tool_tool,
            )

            tools.append(create_execute_mcp_tool_tool())

    def build_llm_params(
        self,
        messages: list,
        state: State,
        tools: list[ChatCompletionToolParam],
    ) -> dict:
        tool_choice = self._determine_tool_choice(messages, state)

        # NOTE: We inject control/status messages *after* tool selection so
        # tool selection heuristics see the original user/assistant content.

        # Cache check_tools output — only recompute when tools or model changes
        # Invalidate cache when tool selection changes the list
        current_model = self._llm.config.model if self._llm else ''
        # Stringify names so cache keys work with MagicMock-based tests and odd payloads.
        tool_fingerprint = ','.join(
            str(
                (t.get('function') or {}).get('name', '') if isinstance(t, dict) else ''
            )
            for t in tools
        )
        cache_key = f'{current_model}:{tool_fingerprint}'
        if self._checked_tools_cache is None or self._checked_tools_model != cache_key:
            self._checked_tools_cache = check_tools(tools, self._llm.config)
            self._checked_tools_model = cache_key

        messages = self._inject_turn_status(messages, state)
        _maybe_log_prompt_metrics(messages)
        if messages:
            first = messages[0]
            role = getattr(first, 'role', '')
            if role == 'system':
                for content in getattr(first, 'content', []):
                    text = getattr(content, 'text', '')
                    if '[DEGRADED_MODE_SYSTEM_PROMPT]' in text:
                        logger.error(
                            'Planner detected degraded emergency system prompt. Tool guidance fidelity may be reduced.'
                        )
                        break

        params: dict[str, Any] = {
            'messages': messages,
            'tools': self._checked_tools_cache,
            'stream': True,
        }

        if tool_choice and self._llm_supports_tool_choice():
            params['tool_choice'] = tool_choice

        params['extra_body'] = {
            'metadata': state.to_llm_metadata(
                model_name=(self._llm.config.model or '').strip() or 'unknown',
                agent_name=getattr(state, 'agent_name', 'Orchestrator'),
            )
        }
        return params

    def _inject_turn_status(self, messages: list, state: State) -> list:
        """Inject a dedicated control/status message for the current turn.

        Emits nothing unless a guard subsystem has set `state.planning_directive`.
        When set, a single `<APP_DIRECTIVE>` block is inserted before the last
        user message.
        """
        ts = getattr(state, 'turn_signals', None)
        planning_directive = getattr(ts, 'planning_directive', None) if ts else None
        if planning_directive is None:
            extra_data = getattr(state, 'extra_data', {}) or {}
            planning_directive = extra_data.get('planning_directive')

        if not planning_directive:
            return messages
        status = f'<APP_DIRECTIVE>\n{planning_directive}\n</APP_DIRECTIVE>'
        return self._apply_control_message(messages, status)

    def _apply_control_message(self, messages: list, status: str) -> list:
        """Attach turn control either as a second system message or merged into primary."""
        if getattr(self._config, 'merge_control_system_into_primary', False):
            return self._merge_control_into_primary_system(messages, status)
        return self._insert_control_message(messages, status)

    def _merge_control_into_primary_system(self, messages: list, status: str) -> list:
        """Append control/status to the first string system message; else fall back."""
        msgs = list(messages)
        for i, msg in enumerate(msgs):
            if not isinstance(msg, dict) or msg.get('role') != 'system':
                continue
            content = msg.get('content', '')
            if not isinstance(content, str):
                return self._insert_control_message(messages, status)
            sep = '\n\n' if content.strip() else ''
            msgs[i] = {**msg, 'content': f'{content}{sep}{status}'}
            return msgs
        return self._insert_control_message(messages, status)

    @staticmethod
    def _insert_control_message(messages: list, status: str) -> list:
        """Insert control message just before the last user message."""
        msgs = list(messages)
        insert_at = len(msgs)
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i], dict) and msgs[i].get('role') == 'user':
                insert_at = i
                break
        msgs.insert(insert_at, {'role': 'system', 'content': status})
        return msgs

    def _determine_tool_choice(self, messages: list, state: State) -> str | dict | None:
        last_user_msg = self._get_last_user_message(messages)
        if not last_user_msg:
            return 'auto'

        # Let the LLM decide whether to use tools — "auto" is more robust
        # than brittle regex-based question/action classification.
        return 'auto'

    def _llm_supports_tool_choice(self) -> bool:
        try:
            model = (self._llm.config.model or '').strip()
            if not model:
                return False
            return supports_tool_choice(model)
        except Exception:
            return False

    def _get_last_user_message(self, messages: list) -> str | None:
        for message in reversed(messages):
            if isinstance(message, dict) and message.get('role') == 'user':
                content = message.get('content', '')
                # Skip workspace-context / knowledge-recall injections so that
                # simple greetings like "hello" are still recognized even after
                # the recall observation inserts a long synthetic user message.
                if isinstance(content, str) and any(
                    marker in content for marker in _INJECTED_MSG_MARKERS
                ):
                    continue
                return content
        return None
