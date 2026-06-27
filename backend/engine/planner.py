from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from backend.core import json_compat as json
from backend.core.interaction_modes import (
    CHAT_MODE_ALLOWED_TOOLS,
    PLAN_MODE,
    PLAN_MODE_ALLOWED_TOOLS,
    is_chat_mode,
    normalize_interaction_mode,
)
from backend.core.logging.logger import app_logger as logger
from backend.inference.catalog.catalog_loader import (
    supports_function_calling,
    supports_tool_choice,
)
from backend.inference.llm.utils import check_tools, get_token_count

ChatCompletionToolParam = Any

# All public file tools use native provider tool calls. Legacy free-form file
# transports are intentionally not part of the model-facing path.
CODE_PAYLOAD_TOOLS: frozenset[str] = frozenset()

if TYPE_CHECKING:
    from backend.engine.contracts import NoopSafetyManager
    from backend.inference.llm import LLM
    from backend.orchestration.state.state import State


def _external_discovery_hint(*, enable_web: bool, enable_docs: bool) -> str:
    parts: list[str] = []
    if enable_web:
        parts.append('`web_search` / `web_fetch`')
    if enable_docs:
        parts.append('`docs_resolve` / `docs_query`')
    if not parts:
        return ''
    return f' (including {" and ".join(parts)} when external context helps)'


# Markers that appear only in system-injected user messages (workspace context,
# playbook knowledge, knowledge-base results) — never in human-typed messages.
_INJECTED_MSG_MARKERS = (
    '<RUNTIME_INFORMATION>',
    '<REPOSITORY_INFO>',
    '<REPOSITORY_INSTRUCTIONS>',
    '<CONVERSATION_INSTRUCTIONS>',
    '<EXTRA_INFO>',
)


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


def _message_text(message: dict[str, Any]) -> str:
    content = message.get('content', '')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get('text') or item))
            else:
                parts.append(str(getattr(item, 'text', item)))
        return '\n'.join(part for part in parts if part)
    return str(content)


def _message_contains(message: dict[str, Any], marker: str) -> bool:
    return marker in _message_text(message)


def _is_static_prompt_message(message: dict[str, Any]) -> bool:
    role = message.get('role')
    if role == 'system':
        return True
    if role != 'user':
        return False
    text = _message_text(message)
    return any(marker in text for marker in _INJECTED_MSG_MARKERS)


class OrchestratorPlanner:
    """Assembles tools, messages, and LLM request payloads for Orchestrator."""

    def __init__(
        self,
        config,
        llm: LLM,
        safety_manager: 'NoopSafetyManager',
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
        self._add_web_tools(tools)
        self._add_docs_tools(tools)
        self._add_editor_tools(tools)
        self._add_execute_mcp_tool_tool(tools)

        mode = self._current_mode()
        tools = self._filter_tools_for_mode(tools, mode)

        tool_names = [self._tool_name(t) for t in tools]
        logger.info(
            'build_toolset: mode=%r config.mode=%r tools=%r',
            mode,
            getattr(self._config, 'mode', 'N/A'),
            tool_names,
            extra={'msg_type': 'PLANNER_TOOLSET'},
        )

        from backend.engine.tools.param_defs import relax_security_risk_in_tools

        tools = relax_security_risk_in_tools(
            tools, getattr(self._config, 'autonomy_level', 'balanced')
        )

        # Invalidate cached checked-tools when toolset is rebuilt
        self._checked_tools_cache = None
        return tools

    def _current_mode(self) -> str:
        return normalize_interaction_mode(getattr(self._config, 'mode', 'agent'))

    @staticmethod
    def _tool_name(tool: ChatCompletionToolParam) -> str:
        return str((tool.get('function') or {}).get('name') or '')

    def _filter_tools_for_mode(
        self,
        tools: list[ChatCompletionToolParam],
        mode: str,
    ) -> list[ChatCompletionToolParam]:
        if mode == PLAN_MODE:
            return self._filter_plan_mode_tools(tools)
        if is_chat_mode(mode):
            return [
                tool
                for tool in tools
                if self._tool_name(tool) in CHAT_MODE_ALLOWED_TOOLS
            ]
        return tools

    def _filter_plan_mode_tools(
        self,
        tools: list[ChatCompletionToolParam],
    ) -> list[ChatCompletionToolParam]:
        return [
            tool for tool in tools if self._tool_name(tool) in PLAN_MODE_ALLOWED_TOOLS
        ]

    def partition_tools(
        self, tools: list[ChatCompletionToolParam]
    ) -> tuple[list[ChatCompletionToolParam], list[ChatCompletionToolParam]]:
        """Return native tools only; raw file transports are disabled."""
        if not self._llm_supports_function_calling():
            # Non-native models still use the generic tool-call text fallback,
            # but no file-specific free-form file block is injected.
            return [], tools

        native: list[ChatCompletionToolParam] = []
        xml: list[ChatCompletionToolParam] = []
        for tool in tools:
            name = (tool.get('function') or {}).get('name', '')
            if name in CODE_PAYLOAD_TOOLS:
                xml.append(tool)
            else:
                native.append(tool)
        return native, xml

    def _add_core_tools(self, tools: list) -> None:
        self._add_basic_tools(tools)
        self._add_edit_and_search_tools(tools)
        self._add_terminal_and_special_tools(tools)

    def _add_basic_tools(self, tools: list) -> None:
        """Add shell, ask_user, and basic file tools."""
        from backend.engine.tools.bash import create_cmd_run_tool
        from backend.engine.tools.meta_cognition import create_ask_user_tool
        from backend.engine.tools.native_file_tools import (
            create_find_symbols_tool,
            create_read_file_tool,
            create_read_symbols_tool,
        )

        tools.append(create_cmd_run_tool())
        tools.append(create_ask_user_tool())
        tools.append(create_read_file_tool())
        tools.append(create_read_symbols_tool())
        tools.append(create_find_symbols_tool())

    def _add_edit_and_search_tools(self, tools: list) -> None:
        """Add task_tracker, grep, and glob tools."""
        from backend.engine.tools.glob import create_glob_tool
        from backend.engine.tools.grep import create_grep_tool
        from backend.engine.tools.task_tracker import (
            create_task_tracker_tool,
        )

        if getattr(self._config, 'enable_task_tracker_tool', True):
            tools.append(create_task_tracker_tool())
        tools.append(create_grep_tool())
        tools.append(create_glob_tool())

    def _add_terminal_and_special_tools(self, tools: list) -> None:
        """Add search/code-intelligence helpers."""
        self._add_optional_feature_tools(tools)
        self._add_terminal_tools(tools)
        self._add_memory_and_checkpoint_tools(tools)

    def _add_terminal_tools(self, tools: list) -> None:
        """Add terminal manager tool when terminal support is enabled."""
        if getattr(self._config, 'enable_terminal', True):
            from backend.engine.tools.terminal_manager import (
                create_terminal_manager_tool,
            )

            tools.append(create_terminal_manager_tool())
        if getattr(self._config, 'enable_debugger', True):
            from backend.utils.runtime_detect import has_any_debug_adapter

            if not has_any_debug_adapter():
                return
            from backend.engine.tools.debugger import (
                create_debugger_tool,
            )

            tools.append(create_debugger_tool())

    def _add_optional_feature_tools(self, tools: list) -> None:
        """Add code-search helpers."""
        from backend.engine.tools.analyze_project_structure import (
            create_analyze_project_structure_tool,
        )
        from backend.engine.tools.lsp_query import create_lsp_query_tool

        tools.append(create_analyze_project_structure_tool())

        if getattr(self._config, 'enable_lsp_query', True):
            from backend.utils.runtime_detect import has_any_lsp_server

            if has_any_lsp_server():
                tools.append(create_lsp_query_tool())

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
        """Compatibility no-op; ask_user is part of the core simplified toolset."""
        return

    def _add_browsing_tool(self, tools: list) -> None:
        from backend.utils.optional_extras import browser_tool_enabled

        if not browser_tool_enabled(self._config):
            return
        from backend.engine.tools.browser_native import create_browser_tool

        tools.append(create_browser_tool())

    def _add_web_tools(self, tools: list) -> None:
        if not getattr(self._config, 'enable_web', True):
            return
        from backend.engine.tools.web_tools import (
            create_web_fetch_tool,
            create_web_search_tool,
        )

        tools.append(create_web_search_tool())
        tools.append(create_web_fetch_tool())

    def _add_docs_tools(self, tools: list) -> None:
        if not getattr(self._config, 'enable_docs', True):
            return
        from backend.engine.tools.docs_tools import (
            create_docs_query_tool,
            create_docs_resolve_tool,
        )

        tools.append(create_docs_resolve_tool())
        tools.append(create_docs_query_tool())

    def _add_editor_tools(self, tools: list) -> None:
        if getattr(self._config, 'enable_editor', True):
            from backend.engine.tools.native_file_tools import (
                create_create_file_tool,
                create_multiedit_tool,
                create_replace_string_tool,
                create_undo_last_edit_tool,
            )

            tools.append(create_create_file_tool())
            tools.append(create_replace_string_tool())
            tools.append(create_multiedit_tool())
            tools.append(create_undo_last_edit_tool())

    def _add_execute_mcp_tool_tool(self, tools: list) -> None:
        from backend.engine.tools.execute_mcp_tool import (
            create_execute_mcp_tool_tool,
        )

        tools.append(create_execute_mcp_tool_tool())

    def _add_memory_and_checkpoint_tools(self, tools: list) -> None:
        if getattr(self._config, 'enable_checkpoints', True):
            from backend.engine.tools.checkpoint import create_checkpoint_tool

            tools.append(create_checkpoint_tool())
        if getattr(self._config, 'enable_working_memory', True):
            from backend.engine.tools.memory import create_memory_tool
            from backend.utils.optional_extras import vector_memory_enabled

            tools.append(
                create_memory_tool(
                    include_semantic_recall=vector_memory_enabled(self._config)
                )
            )

    def _refresh_checked_tools_cache(
        self, tools: list[ChatCompletionToolParam]
    ) -> None:
        current_model = self._llm.config.model if self._llm else ''
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

    @staticmethod
    def _warn_if_degraded_emergency_prompt(messages: list) -> None:
        if not messages:
            return
        first = messages[0]
        role = getattr(first, 'role', '')
        if role != 'system':
            return
        for content in getattr(first, 'content', []):
            text = getattr(content, 'text', '')
            if '[DEGRADED_MODE_SYSTEM_PROMPT]' in text:
                logger.error(
                    'Planner detected degraded emergency system prompt. Tool guidance fidelity may be reduced.'
                )
                break

    def build_llm_params(
        self,
        messages: list,
        state: State,
        tools: list[ChatCompletionToolParam],
    ) -> dict:
        tool_choice = self._determine_tool_choice(messages, state)
        mode = self._active_mode_for_state(state)
        messages = self._inject_turn_status(messages, state)
        messages = self._inject_coding_preflight(messages, state, mode)
        tools = self._filter_tools_for_mode(tools, mode)
        messages = self._inject_mode_instructions(messages, state, mode)
        _maybe_log_prompt_metrics(messages)
        self._warn_if_degraded_emergency_prompt(messages)
        self._log_debug_mode_info(messages, state, mode)

        params: dict[str, Any] = {'messages': messages, 'stream': True}
        params = self._configure_tool_routing(params, tools, messages, tool_choice)
        params['extra_body'] = {
            'metadata': state.to_llm_metadata(
                model_name=(self._llm.config.model or '').strip() or 'unknown',
                agent_name=getattr(state, 'agent_name', 'Orchestrator'),
            )
        }
        self._attach_prompt_accounting(params, state)
        return params

    def _attach_prompt_accounting(self, params: dict[str, Any], state: State) -> None:
        accounting = self._build_prompt_accounting(params)
        params['_prompt_accounting'] = accounting
        try:
            state.set_extra(
                'prompt_token_accounting',
                accounting,
                source='OrchestratorPlanner',
            )
        except Exception:
            logger.debug('Failed to persist prompt token accounting', exc_info=True)
        logger.info(
            'LLM prompt composition: %s',
            json.dumps(accounting, sort_keys=True, default=str),
        )

    def _build_prompt_accounting(self, params: dict[str, Any]) -> dict[str, int]:
        messages = params.get('messages')
        if not isinstance(messages, list):
            messages = []
        tools = params.get('tools')
        if not isinstance(tools, list):
            tools = []

        message_tokens = self._count_messages(messages)
        static_prompt_tokens = self._count_messages(
            [msg for msg in messages if _is_static_prompt_message(msg)]
        )
        context_packet_tokens = self._count_messages(
            [msg for msg in messages if _message_contains(msg, '<CONTEXT_PACKET>')]
        )
        tool_schema_tokens = self._count_tool_schema_tokens(tools)
        full_request_tokens = message_tokens + tool_schema_tokens
        dynamic_history_tokens = max(
            0, message_tokens - static_prompt_tokens - context_packet_tokens
        )
        usable_input = self._usable_input_tokens()
        return {
            'static_prompt_tokens': static_prompt_tokens,
            'tool_schema_tokens': tool_schema_tokens,
            'dynamic_history_tokens': dynamic_history_tokens,
            'context_packet_tokens': context_packet_tokens,
            'usable_input_tokens': usable_input,
            'full_request_tokens': full_request_tokens,
        }

    def _count_messages(self, messages: list[dict[str, Any]]) -> int:
        if not messages:
            return 0
        try:
            return get_token_count(
                messages,
                model=(self._llm.config.model or '').strip() or 'gpt-4o',
                custom_tokenizer=getattr(self._llm.config, 'custom_tokenizer', None),
            )
        except Exception:
            return max(1, len(str(messages)) // 4)

    def _count_tool_schema_tokens(self, tools: list[dict[str, Any]]) -> int:
        if not tools:
            return 0
        try:
            payload = json.dumps(tools, sort_keys=True, default=str)
        except Exception:
            payload = str(tools)
        return self._count_messages([{'role': 'system', 'content': payload}])

    def _usable_input_tokens(self) -> int:
        try:
            from backend.inference.capabilities.context_limits import limits_from_config

            limits = limits_from_config(self._llm.config, unknown_default=True)
            return int(limits.usable_input_tokens or 0)
        except Exception:
            return 0

    def _log_debug_mode_info(self, messages: list, state: State, mode: str) -> None:
        mode_injected = None
        for i in range(len(messages) - 1, -1, -1):
            content = messages[i].get('content', '')
            if isinstance(content, str) and '===' in content and 'MODE' in content:
                mode_injected = content[:200]
                break
        logger.info(
            'turn mode=%s active_run_mode=%s | injected_msg=%r',
            mode,
            (getattr(state, 'extra_data', {}) or {}).get('active_run_mode', 'N/A'),
            mode_injected,
            extra={'msg_type': 'PLANNER_TURN'},
        )

    def _configure_tool_routing(
        self,
        params: dict,
        tools: list,
        messages: list,
        tool_choice: str | dict[Any, Any] | None,
    ) -> dict:
        native_tools, xml_tools = self.partition_tools(tools)
        if self._llm_supports_function_calling():
            self._refresh_checked_tools_cache(native_tools)
            params['tools'] = self._checked_tools_cache
        if xml_tools:
            messages = self._inject_xml_tool_descriptions(messages, xml_tools)
            params['messages'] = messages
        if 'tools' in params and tool_choice and self._llm_supports_tool_choice():
            params['tool_choice'] = tool_choice
        return params

    @staticmethod
    def _inject_xml_tool_descriptions(
        messages: list, xml_tools: list[ChatCompletionToolParam]
    ) -> list:
        """Append generic text fallback tool descriptions for non-native models."""
        from backend.inference.fn_call import (
            convert_tools_to_description,
        )

        formatted = convert_tools_to_description(xml_tools)
        suffix = (
            '\n\n<TOOL_CALL_FORMAT>\n'
            'Use the available tools by emitting valid tool calls with arguments '
            'matching the registered schemas.\n'
            f'{formatted}\n'
            'RULES:\n'
            '- find_symbols discovers symbol candidates without reading full bodies.\n'
            '- read inspects a file (optional line range) or one/more symbol bodies via symbols[].\n'
            '- create creates a new file.\n'
            '- replace_string performs one exact text replacement, insertion, or deletion in one file.\n'
            '- multiedit performs atomic batch refactoring (multiple replace_string ops across one or more files).\n'
            '- File API rule: one change on one file -> replace_string; anything batched -> multiedit.\n'
            '</TOOL_CALL_FORMAT>'
        )

        msgs = list(messages)
        for i, msg in enumerate(msgs):
            if isinstance(msg, dict) and msg.get('role') == 'system':
                content = msg.get('content', '')
                if isinstance(content, str):
                    msgs[i] = {**msg, 'content': content + suffix}
                    return msgs
                if isinstance(content, list) and content:
                    last = content[-1]
                    if isinstance(last, dict) and last.get('type') == 'text':
                        content = list(content)
                        content[-1] = {**last, 'text': last.get('text', '') + suffix}
                        msgs[i] = {**msg, 'content': content}
                        return msgs
        # No system message found — prepend one
        msgs.insert(0, {'role': 'system', 'content': suffix})
        return msgs

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

    def _inject_coding_preflight(self, messages: list, state: State, mode: str) -> list:
        """Inject a lightweight first-turn coding-task preflight when enabled."""
        enabled = getattr(self._config, 'enable_coding_preflight', True)
        if enabled is False:
            return messages
        try:
            from backend.context.coding_preflight import build_coding_preflight_block

            block = build_coding_preflight_block(
                messages,
                state,
                self._config,
                mode=mode,
            )
        except Exception:
            logger.debug('Coding preflight generation failed', exc_info=True)
            return messages
        if not block:
            return messages
        return self._apply_control_message(messages, block)

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

    def _llm_supports_function_calling(self) -> bool:
        try:
            model = (self._llm.config.model or '').strip()
            if not model:
                return False
            return supports_function_calling(model)
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

    def _active_mode_for_state(self, state: State | None) -> str:
        extra = getattr(state, 'extra_data', {}) if state is not None else {}
        active_run_mode = (
            extra.get('active_run_mode') if isinstance(extra, dict) else None
        )
        mode = normalize_interaction_mode(active_run_mode) if active_run_mode else None
        if mode:
            logger.debug(
                '_active_mode_for_state: active_run_mode=%r -> %r',
                active_run_mode,
                mode,
            )
            return mode
        fallback = normalize_interaction_mode(getattr(self._config, 'mode', 'agent'))
        logger.debug(
            '_active_mode_for_state: fallback config.mode=%r',
            fallback,
        )
        return fallback

    def _inject_mode_instructions(
        self,
        messages: list,
        state: State,
        mode: str,
    ) -> list:
        if mode == PLAN_MODE:
            return self._inject_plan_mode_instructions(messages, state)
        if is_chat_mode(mode):
            return self._inject_chat_mode_instructions(messages, state)
        return self._inject_agent_mode_instructions(messages, state)

    def _inject_plan_mode_instructions(self, messages: list, state: State) -> list:
        hint = _external_discovery_hint(
            enable_web=bool(getattr(self._config, 'enable_web', True)),
            enable_docs=bool(getattr(self._config, 'enable_docs', True)),
        )
        instruction = (
            '\n\n=== CURRENT MODE: PLAN ===\n'
            'This is the authoritative current-mode instruction for this turn.\n'
            'Current mode: PLAN\n\n'
            f'- Use discovery tools{hint} '
            'to inspect and search the codebase.\n'
            '- Use `ask_user` only when user input is required to continue.\n'
            '- Use `task_tracker` to structure the plan when committing to multi-step work.\n'
            '- Do not edit files or run shell commands.\n'
            '- Write the final plan in plain text when complete; that ends the run.\n'
            '==========================\n'
        )
        return self._apply_control_message(messages, instruction)

    def _inject_agent_mode_instructions(self, messages: list, state: State) -> list:
        # Minimal per-turn mode signal — just enough for the agent to know its mode,
        # like the OS/env one-liner. Full rules are already in the system prompt and tool schemas.
        instruction = '\n\nCurrent mode: AGENT'
        return self._apply_control_message(messages, instruction)

    def _inject_chat_mode_instructions(self, messages: list, state: State) -> list:
        hint = _external_discovery_hint(
            enable_web=bool(getattr(self._config, 'enable_web', True)),
            enable_docs=bool(getattr(self._config, 'enable_docs', True)),
        )
        instruction = (
            '\n\n=== CURRENT MODE: CHAT ===\n'
            'This is the authoritative current-mode instruction for this turn.\n'
            'Current mode: CHAT\n\n'
            f'- Use discovery tools{hint} '
            'to investigate the codebase when grounding helps.\n'
            '- Use `ask_user` only when user input is required to continue.\n'
            '- Do not edit files or run shell commands.\n'
            '- Respond naturally in prose; plain text ends the turn unless you used `ask_user`.\n'
            '==========================\n'
        )
        return self._apply_control_message(messages, instruction)
