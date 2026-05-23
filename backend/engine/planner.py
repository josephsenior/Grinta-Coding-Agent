from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.inference.catalog_loader import (
    supports_function_calling,
    supports_tool_choice,
)
from backend.inference.llm_utils import check_tools

ChatCompletionToolParam = Any

# ── Hybrid XML/Native transport ──────────────────────────────────────────
# File content is no longer routed through provider JSON arguments. Normal
# tools remain native; file edits start with the metadata-only start_file_edit
# tool and capture raw content in isolated EDITOR MODE.
CODE_PAYLOAD_TOOLS: frozenset[str] = frozenset()

if TYPE_CHECKING:
    from backend.core.contracts.state import State
    from backend.inference.llm import LLM

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

        mode = getattr(self._config, 'mode', 'agent')
        if mode in ('chat', 'ask'):
            forbidden_tool_names = {
                'run',
                'terminal_manager',
                'debugger',
                'create_file',
                'undo_last_edit',
                'rename_symbol',
                'delegate_task',
                'blackboard',
                'checkpoint',
                'call_tool_mcp',
                'browser_tool',
                'browse_interactive'
            }
            tools = [t for t in tools if (t.get('function') or {}).get('name') not in forbidden_tool_names]

        # Invalidate cached checked-tools when toolset is rebuilt
        self._checked_tools_cache = None
        return tools

    def partition_tools(
        self, tools: list[ChatCompletionToolParam]
    ) -> tuple[list[ChatCompletionToolParam], list[ChatCompletionToolParam]]:
        """Split tools into native (JSON) and XML (raw-text) groups.

        Code-heavy tools are routed through the pseudo-XML transport so that
        code payloads are carried as raw text between tags — no JSON escaping.
        All other tools use native provider function calling for the benefits
        of constrained decoding.

        Returns ``(native_tools, xml_tools)``.
        """
        if not self._llm_supports_function_calling():
            # Non-native models: everything already goes through XML
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
        """Add cmd, finish, summarize_context, memory, and read-only file tools."""
        from backend.engine.tools.bash import create_cmd_run_tool
        from backend.engine.tools.condensation_request import (
            create_summarize_context_tool,
        )
        from backend.engine.tools.finish import create_finish_tool
        from backend.engine.tools.native_file_tools import (
            create_find_symbol_tool,
            create_read_file_tool,
        )
        from backend.engine.tools.memory_manager import (
            create_memory_manager_tool,
        )
        from backend.engine.tools.note import create_note_tool, create_recall_tool

        tools.append(create_cmd_run_tool())
        if getattr(self._config, 'enable_finish', True):
            tools.append(create_finish_tool())
        if getattr(self._config, 'enable_condensation_request', False):
            tools.append(create_summarize_context_tool())
        if getattr(self._config, 'enable_working_memory', True):
            tools.append(create_memory_manager_tool())
        tools.append(create_note_tool())
        tools.append(create_recall_tool())
        tools.append(create_read_file_tool())
        tools.append(create_find_symbol_tool())

    def _add_edit_and_search_tools(self, tools: list) -> None:
        """Add task_tracker, search_code and read_symbol tools."""
        from backend.engine.tools.read_symbol import (
            create_read_symbol_tool,
        )
        from backend.engine.tools.search_code import (
            create_search_code_tool,
        )
        from backend.engine.tools.task_tracker import (
            create_task_tracker_tool,
        )

        if getattr(self._config, 'enable_task_tracker_tool', False):
            tools.append(create_task_tracker_tool())
        tools.append(create_search_code_tool())
        tools.append(create_read_symbol_tool())

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
        if getattr(self._config, 'enable_debugger', False):
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

        if getattr(self._config, 'enable_lsp_query', True):
            from backend.utils.runtime_detect import has_any_lsp_server

            if has_any_lsp_server():
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
            from backend.engine.tools.native_file_tools import (
                create_create_file_tool,
                create_rename_symbol_tool,
                create_undo_last_edit_tool,
            )

            tools.append(create_create_file_tool())
            tools.append(create_undo_last_edit_tool())
            tools.append(create_rename_symbol_tool())

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

        # NOTE: We inject control/status messages *after* tool selection so
        # tool selection heuristics see the original user/assistant content.

        messages = self._inject_turn_status(messages, state)
        mode = getattr(self._config, 'mode', 'agent')
        if mode not in ('chat', 'ask'):
            messages = self._inject_agent_mode_instructions(messages, state)
        _maybe_log_prompt_metrics(messages)
        self._warn_if_degraded_emergency_prompt(messages)

        params: dict[str, Any] = {
            'messages': messages,
            'stream': True,
        }

        # ── Tool routing ─────────────────────────────────────────────
        # All normal tools are native provider function calls. File content is
        # captured separately in EDITOR MODE after start_file_edit.
        native_tools, xml_tools = self.partition_tools(tools)

        if self._llm_supports_function_calling():
            self._refresh_checked_tools_cache(native_tools)
            params['tools'] = self._checked_tools_cache

        if xml_tools:
            messages = self._inject_xml_tool_descriptions(messages, xml_tools)
            params['messages'] = messages

        if 'tools' in params and tool_choice and self._llm_supports_tool_choice():
            params['tool_choice'] = tool_choice

        params['extra_body'] = {
            'metadata': state.to_llm_metadata(
                model_name=(self._llm.config.model or '').strip() or 'unknown',
                agent_name=getattr(state, 'agent_name', 'Orchestrator'),
            )
        }
        return params

    @staticmethod
    def _inject_xml_tool_descriptions(
        messages: list, xml_tools: list[ChatCompletionToolParam]
    ) -> list:
        """Append pseudo-XML tool format instructions to the system prompt.

        Editor tools are described using the same format that non-native models
        already use, but file edits now route through the two-mode
        ``start_file_edit`` protocol with raw content blocks.
        """
        from backend.inference.fn_call_converter import (
            convert_tools_to_description,
            format_file_editor_xml_examples_for_prompt,
        )

        formatted = convert_tools_to_description(xml_tools)
        xml_examples = format_file_editor_xml_examples_for_prompt()
        # Build the suffix but replace the generic "one function at a time"
        # note with hybrid-specific guidance.
        suffix = (
            '\n\n<FILE_EDITING_TOOL_FORMAT>\n'
            'The `start_file_edit` tool initiates a metadata-only edit transaction. '
            'When the runtime enters FILE EDITOR MODE, emit one `<file_edit>` block '
            'containing raw file content. Do NOT use the standard JSON tool calling '
            'format for file content.\n'
            f'{formatted}\n'
            'Canonical examples (emit one block per message; copy parameter names exactly):\n\n'
            f'{xml_examples}\n\n'
            'RULES:\n'
            '- You may include natural-language reasoning BEFORE the raw-content block.\n'
            '- Do NOT place any text AFTER the closing tag.\n'
            '- Code between tags is written exactly as it should appear in the file.\n'
            '- Always include <parameter=security_risk>LOW|MEDIUM|HIGH</parameter>.\n'
            '- Use the raw-content editor block for file writes; metadata-only for the starter call.\n'
            '- One file-editing call per message.\n'
            '- For multi_edit: use nested raw-content blocks (NOT JSON arrays).\n'
            '- Each block: <path>, <operation>, <content>.\n'
            '- Operations: insert, replace_range, edit_symbol.\n'
            '</FILE_EDITING_TOOL_FORMAT>'
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

    def _inject_agent_mode_instructions(self, messages: list, state: State) -> list:
        token = getattr(self._agent, '_current_delimiter_token', None) or 'GRINTA_TOKEN'
        instruction = (
            "\n\n=== STRICTOR AGENT MODE PROTOCOL ===\n"
            "You are running in AGENT MODE. In this mode, direct plain text prose/responses "
            "are strictly forbidden. Do not write explanations, thoughts, or comments in direct prose. "
            "Your output must be exactly one of the following:\n"
            "1. A real tool/function call (using the native function calling mechanism).\n"
            "2. A communicate_with_user tool call (to ask questions, clarify, or report blockers).\n"
            "3. A finish tool call (to end the task successfully).\n"
            "4. Exactly one valid EDIT_FILE block using the turn's delimiter token: {token}.\n\n"
            "To edit an existing file, you must output exactly one valid EDIT_FILE block with this format (no markdown code fences around it):\n\n"
            "EDIT_FILE\n"
            "path: relative/path/to/file\n"
            "command: command_name\n"
            "metadata_key: metadata_value\n\n"
            "RAW_LINES {token}\n"
            "raw source content here\n"
            "END_RAW_LINES {token}\n\n"
            "EDIT_FILE block rules:\n"
            "- path is required.\n"
            "- command is required (must be exactly one of: insert, replace_range, edit_symbol, edit_symbols, multi_edit).\n"
            "- All other metadata fields are command-specific.\n"
            "- Use colon syntax (key: value) for headers.\n"
            "- The content between RAW_LINES and END_RAW_LINES is literal raw source text (no escaping required, quotes/braces/indentation are preserved exactly).\n"
            "- Do not add any text or explanation before or after the EDIT_FILE block.\n"
            "- One edit block per response.\n"
            "=====================================\n"
        ).replace("{token}", token)
        
        return self._apply_control_message(messages, instruction)
