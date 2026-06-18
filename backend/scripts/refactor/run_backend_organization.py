"""Move loose backend package-root modules into dedicated subpackages."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / 'backend'

# --- CLI (orphans → existing subfolders per CLI_MODULE_MAP) ---

CLI_MOVES: dict[str, str] = {
    'syntax_theme.py': 'theme/syntax_theme.py',
    'layout_tokens.py': 'display/layout_tokens.py',
    'text_truncation.py': 'display/text_truncation.py',
    'path_links.py': 'display/path_links.py',
    'orient_tools.py': 'tool_display/orient_tools.py',
    'repl_noninteractive.py': 'repl/noninteractive.py',
    'repl_debug.py': 'repl/debug.py',
    'storage_cleanup.py': 'session/storage_cleanup.py',
}

CLI_IMPORTS: list[tuple[str, str]] = [
    ('backend.cli.syntax_theme', 'backend.cli.theme.syntax_theme'),
    ('backend.cli.layout_tokens', 'backend.cli.display.layout_tokens'),
    ('backend.cli.text_truncation', 'backend.cli.display.text_truncation'),
    ('backend.cli.path_links', 'backend.cli.display.path_links'),
    ('backend.cli.orient_tools', 'backend.cli.tool_display.orient_tools'),
    ('backend.cli.repl_noninteractive', 'backend.cli.repl.noninteractive'),
    ('backend.cli.repl_debug', 'backend.cli.repl.debug'),
    ('backend.cli.storage_cleanup', 'backend.cli.session.storage_cleanup'),
]

# --- context/context_pipeline package ---

CONTEXT_PIPELINE_MOVES: dict[str, str] = {
    'context_pipeline.py': 'context_pipeline/__init__.py',
    'context_pipeline_types.py': 'context_pipeline/types.py',
    'context_pipeline_helpers.py': 'context_pipeline/helpers.py',
    'context_pipeline_core.py': 'context_pipeline/core.py',
    'context_pipeline_core_base.py': 'context_pipeline/core_base.py',
    'context_pipeline_core_prepare.py': 'context_pipeline/core_prepare.py',
    'context_pipeline_core_prompt.py': 'context_pipeline/core_prompt.py',
    'context_pipeline_core_compact.py': 'context_pipeline/core_compact.py',
    'context_pipeline_core_state.py': 'context_pipeline/core_state.py',
    'context_pipeline_core_gates.py': 'context_pipeline/core_gates.py',
}

CONTEXT_PIPELINE_IMPORTS: list[tuple[str, str]] = [
    ('backend.context.context_pipeline_types', 'backend.context.context_pipeline.types'),
    ('backend.context.context_pipeline_helpers', 'backend.context.context_pipeline.helpers'),
    ('backend.context.context_pipeline_core_base', 'backend.context.context_pipeline.core_base'),
    ('backend.context.context_pipeline_core_prepare', 'backend.context.context_pipeline.core_prepare'),
    ('backend.context.context_pipeline_core_prompt', 'backend.context.context_pipeline.core_prompt'),
    ('backend.context.context_pipeline_core_compact', 'backend.context.context_pipeline.core_compact'),
    ('backend.context.context_pipeline_core_state', 'backend.context.context_pipeline.core_state'),
    ('backend.context.context_pipeline_core_gates', 'backend.context.context_pipeline.core_gates'),
    ('backend.context.context_pipeline_core', 'backend.context.context_pipeline.core'),
]

# --- context/canonical_state package ---

CANONICAL_STATE_MOVES: dict[str, str] = {
    'canonical_state.py': 'canonical_state/__init__.py',
    'canonical_state_types.py': 'canonical_state/types.py',
    'canonical_state_ops.py': 'canonical_state/ops.py',
    'canonical_state_private.py': 'canonical_state/private.py',
}

CANONICAL_STATE_IMPORTS: list[tuple[str, str]] = [
    ('backend.context.canonical_state_types', 'backend.context.canonical_state.types'),
    ('backend.context.canonical_state_ops', 'backend.context.canonical_state.ops'),
    ('backend.context.canonical_state_private', 'backend.context.canonical_state.private'),
]

# --- inference/llm package (split siblings) ---

LLM_MOVES: dict[str, str] = {
    'llm.py': 'llm/__init__.py',
    'llm_core.py': 'llm/core.py',
    'llm_config.py': 'llm/config.py',
    'llm_exceptions.py': 'llm/exceptions.py',
    'llm_stream.py': 'llm/stream.py',
    'llm_utils.py': 'llm/utils.py',
}

LLM_IMPORTS: list[tuple[str, str]] = [
    ('backend.inference.llm_core', 'backend.inference.llm.core'),
    ('backend.inference.llm_config', 'backend.inference.llm.config'),
    ('backend.inference.llm_exceptions', 'backend.inference.llm.exceptions'),
    ('backend.inference.llm_stream', 'backend.inference.llm.stream'),
    ('backend.inference.llm_utils', 'backend.inference.llm.utils'),
]

# --- inference/direct client provider ops ---

PROVIDER_MOVES: dict[str, str] = {
    'direct_clients_openai_ops.py': 'providers/openai_ops.py',
    'direct_clients_anthropic_ops.py': 'providers/anthropic_ops.py',
    'direct_clients_gemini_ops.py': 'providers/gemini_ops.py',
    'direct_clients_opencode_gemini_ops.py': 'providers/opencode_gemini_ops.py',
    'direct_clients_opencode_responses_ops.py': 'providers/opencode_responses_ops.py',
}

PROVIDER_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.inference.direct_clients_openai_ops',
        'backend.inference.providers.openai_ops',
    ),
    (
        'backend.inference.direct_clients_anthropic_ops',
        'backend.inference.providers.anthropic_ops',
    ),
    (
        'backend.inference.direct_clients_gemini_ops',
        'backend.inference.providers.gemini_ops',
    ),
    (
        'backend.inference.direct_clients_opencode_gemini_ops',
        'backend.inference.providers.opencode_gemini_ops',
    ),
    (
        'backend.inference.direct_clients_opencode_responses_ops',
        'backend.inference.providers.opencode_responses_ops',
    ),
]

# --- context/memory package ---

MEMORY_MOVES: dict[str, str] = {
    'agent_memory.py': 'memory/agent_memory.py',
    'conversation_memory.py': 'memory/conversation_memory.py',
    'session_memory.py': 'memory/session_memory.py',
    'memory_types.py': 'memory/types.py',
    'working_set.py': 'memory/working_set.py',
    'session_context.py': 'memory/session_context.py',
}

MEMORY_IMPORTS: list[tuple[str, str]] = [
    ('backend.context.agent_memory', 'backend.context.memory.agent_memory'),
    ('backend.context.conversation_memory', 'backend.context.memory.conversation_memory'),
    ('backend.context.session_memory', 'backend.context.memory.session_memory'),
    ('backend.context.memory_types', 'backend.context.memory.types'),
    ('backend.context.working_set', 'backend.context.memory.working_set'),
    ('backend.context.session_context', 'backend.context.memory.session_context'),
]

# --- context/processors ---

PROCESSORS_MOVES: dict[str, str] = {
    'action_processors.py': 'processors/action_processors.py',
    'observation_processors.py': 'processors/observation_processors.py',
}

PROCESSORS_IMPORTS: list[tuple[str, str]] = [
    ('backend.context.action_processors', 'backend.context.processors.action_processors'),
    ('backend.context.observation_processors', 'backend.context.processors.observation_processors'),
]

# --- context/compaction (distinct from compactor/ strategies) ---

COMPACTION_MOVES: dict[str, str] = {
    'compact_boundary.py': 'compaction/compact_boundary.py',
    'microcompact.py': 'compaction/microcompact.py',
    'compaction_finalizer.py': 'compaction/compaction_finalizer.py',
    'condensed_history.py': 'compaction/condensed_history.py',
    'pre_condensation_snapshot.py': 'compaction/pre_condensation_snapshot.py',
}

COMPACTION_IMPORTS: list[tuple[str, str]] = [
    ('backend.context.compact_boundary', 'backend.context.compaction.compact_boundary'),
    ('backend.context.microcompact', 'backend.context.compaction.microcompact'),
    ('backend.context.compaction_finalizer', 'backend.context.compaction.compaction_finalizer'),
    ('backend.context.condensed_history', 'backend.context.compaction.condensed_history'),
    ('backend.context.pre_condensation_snapshot', 'backend.context.compaction.pre_condensation_snapshot'),
]

# --- context/prompt ---

PROMPT_MOVES: dict[str, str] = {
    'prompt_window.py': 'prompt/prompt_window.py',
    'prompt_assembly.py': 'prompt/prompt_assembly.py',
    'context_packet.py': 'prompt/context_packet.py',
    'message_formatting.py': 'prompt/message_formatting.py',
}

PROMPT_IMPORTS: list[tuple[str, str]] = [
    ('backend.context.prompt_window', 'backend.context.prompt.prompt_window'),
    ('backend.context.prompt_assembly', 'backend.context.prompt.prompt_assembly'),
    ('backend.context.context_packet', 'backend.context.prompt.context_packet'),
    ('backend.context.message_formatting', 'backend.context.prompt.message_formatting'),
]

# --- ledger/stream package (stream.py becomes __init__.py) ---

LEDGER_STREAM_MOVES: dict[str, str] = {
    'persistence.py': 'stream/persistence.py',
    'durable_writer.py': 'stream/durable_writer.py',
    'backpressure.py': 'stream/backpressure.py',
    'coalescing.py': 'stream/coalescing.py',
    'compaction.py': 'stream/compaction.py',
    'nested_event_store.py': 'stream/nested_event_store.py',
    'async_event_store_wrapper.py': 'stream/async_event_store_wrapper.py',
    'stream_stats.py': 'stream/stream_stats.py',
    'stream.py': 'stream/__init__.py',
}

LEDGER_STREAM_IMPORTS: list[tuple[str, str]] = [
    ('backend.ledger.persistence', 'backend.ledger.stream.persistence'),
    ('backend.ledger.durable_writer', 'backend.ledger.stream.durable_writer'),
    ('backend.ledger.backpressure', 'backend.ledger.stream.backpressure'),
    ('backend.ledger.coalescing', 'backend.ledger.stream.coalescing'),
    ('backend.ledger.compaction', 'backend.ledger.stream.compaction'),
    ('backend.ledger.nested_event_store', 'backend.ledger.stream.nested_event_store'),
    (
        'backend.ledger.async_event_store_wrapper',
        'backend.ledger.stream.async_event_store_wrapper',
    ),
    ('backend.ledger.stream_stats', 'backend.ledger.stream.stream_stats'),
]

# --- execution/runtime ---

EXECUTION_RUNTIME_MOVES: dict[str, str] = {
    'runtime_manager.py': 'runtime/manager.py',
    'runtime_pool.py': 'runtime/pool.py',
    'runtime_factory.py': 'runtime/factory.py',
    'orchestrator.py': 'runtime/orchestrator.py',
}

EXECUTION_RUNTIME_IMPORTS: list[tuple[str, str]] = [
    ('backend.execution.runtime_manager', 'backend.execution.runtime.manager'),
    ('backend.execution.runtime_pool', 'backend.execution.runtime.pool'),
    ('backend.execution.runtime_factory', 'backend.execution.runtime.factory'),
    ('backend.execution.orchestrator', 'backend.execution.runtime.orchestrator'),
]

# --- inference/capabilities ---

CAPABILITIES_MOVES: dict[str, str] = {
    'model_features.py': 'capabilities/model_features.py',
    'provider_capabilities.py': 'capabilities/provider_capabilities.py',
    'param_profiles.py': 'capabilities/param_profiles.py',
    'context_limits.py': 'capabilities/context_limits.py',
    'capabilities.py': 'capabilities/__init__.py',
}

CAPABILITIES_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.inference.provider_capabilities',
        'backend.inference.capabilities.provider_capabilities',
    ),
    ('backend.inference.model_features', 'backend.inference.capabilities.model_features'),
    ('backend.inference.param_profiles', 'backend.inference.capabilities.param_profiles'),
    ('backend.inference.context_limits', 'backend.inference.capabilities.context_limits'),
]

# --- inference/caching (replace prompt_caching before prompt_cache) ---

CACHING_MOVES: dict[str, str] = {
    'prompt_caching.py': 'caching/prompt_caching.py',
    'prompt_cache.py': 'caching/prompt_cache.py',
    'gemini_cache.py': 'caching/gemini_cache.py',
}

CACHING_IMPORTS: list[tuple[str, str]] = [
    ('backend.inference.prompt_caching', 'backend.inference.caching.prompt_caching'),
    ('backend.inference.prompt_cache', 'backend.inference.caching.prompt_cache'),
    ('backend.inference.gemini_cache', 'backend.inference.caching.gemini_cache'),
]

# --- execution/aes (action execution server helpers) ---

EXECUTION_AES_MOVES: dict[str, str] = {
    'action_execution_server_helpers.py': 'aes/helpers.py',
    'file_operations.py': 'aes/file_operations.py',
    'structured_edit_errors.py': 'aes/structured_edit_errors.py',
    'security_enforcement.py': 'aes/security_enforcement.py',
}

EXECUTION_AES_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.execution.action_execution_server_helpers',
        'backend.execution.aes.helpers',
    ),
    ('backend.execution.file_operations', 'backend.execution.aes.file_operations'),
    (
        'backend.execution.structured_edit_errors',
        'backend.execution.aes.structured_edit_errors',
    ),
    (
        'backend.execution.security_enforcement',
        'backend.execution.aes.security_enforcement',
    ),
]

# --- execution/server (HTTP routes and file viewer) ---

EXECUTION_SERVER_MOVES: dict[str, str] = {
    'server_routes.py': 'server/routes.py',
    'server_utils.py': 'server/utils.py',
    'file_viewer_server.py': 'server/file_viewer_server.py',
}

EXECUTION_SERVER_IMPORTS: list[tuple[str, str]] = [
    ('backend.execution.server_routes', 'backend.execution.server.routes'),
    ('backend.execution.server_utils', 'backend.execution.server.utils'),
    (
        'backend.execution.file_viewer_server',
        'backend.execution.server.file_viewer_server',
    ),
]

# --- ledger/infra ---

LEDGER_INFRA_MOVES: dict[str, str] = {
    'adapter.py': 'infra/adapter.py',
    'config.py': 'infra/config.py',
    'integrity.py': 'infra/integrity.py',
    'secret_masker.py': 'infra/secret_masker.py',
    'tool.py': 'infra/tool.py',
}

LEDGER_INFRA_IMPORTS: list[tuple[str, str]] = [
    ('backend.ledger.adapter', 'backend.ledger.infra.adapter'),
    ('backend.ledger.config', 'backend.ledger.infra.config'),
    ('backend.ledger.integrity', 'backend.ledger.infra.integrity'),
    ('backend.ledger.secret_masker', 'backend.ledger.infra.secret_masker'),
    ('backend.ledger.tool', 'backend.ledger.infra.tool'),
]

# --- utils/treesitter ---

UTILS_TREESITTER_MOVES: dict[str, str] = {
    '_tse_errors.py': 'treesitter/_tse_errors.py',
    '_tse_languages.py': 'treesitter/_tse_languages.py',
    '_tse_query.py': 'treesitter/_tse_query.py',
    '_tse_runtime.py': 'treesitter/_tse_runtime.py',
    '_tse_types.py': 'treesitter/_tse_types.py',
    'treesitter_editor.py': 'treesitter/treesitter_editor.py',
    'syntax_check.py': 'treesitter/syntax_check.py',
    'chunk_localizer.py': 'treesitter/chunk_localizer.py',
}

UTILS_TREESITTER_IMPORTS: list[tuple[str, str]] = [
    ('backend.utils._tse_errors', 'backend.utils.treesitter._tse_errors'),
    ('backend.utils._tse_languages', 'backend.utils.treesitter._tse_languages'),
    ('backend.utils._tse_query', 'backend.utils.treesitter._tse_query'),
    ('backend.utils._tse_runtime', 'backend.utils.treesitter._tse_runtime'),
    ('backend.utils._tse_types', 'backend.utils.treesitter._tse_types'),
    ('backend.utils.treesitter_editor', 'backend.utils.treesitter.treesitter_editor'),
    ('backend.utils.syntax_check', 'backend.utils.treesitter.syntax_check'),
    ('backend.utils.chunk_localizer', 'backend.utils.treesitter.chunk_localizer'),
]

# --- utils/async_helpers (async is a reserved keyword — cannot use utils/async/) ---

UTILS_ASYNC_HELPERS_MOVES: dict[str, str] = {
    'async_utils.py': 'async_helpers/async_utils.py',
    'retry.py': 'async_helpers/retry.py',
    'circuit_breaker.py': 'async_helpers/circuit_breaker.py',
    'tenacity_metrics.py': 'async_helpers/tenacity_metrics.py',
    'tenacity_stop.py': 'async_helpers/tenacity_stop.py',
    'subprocess_bridge.py': 'async_helpers/subprocess_bridge.py',
}

UTILS_ASYNC_HELPERS_IMPORTS: list[tuple[str, str]] = [
    ('backend.utils.async_utils', 'backend.utils.async_helpers.async_utils'),
    ('backend.utils.subprocess_bridge', 'backend.utils.async_helpers.subprocess_bridge'),
    ('backend.utils.circuit_breaker', 'backend.utils.async_helpers.circuit_breaker'),
    ('backend.utils.tenacity_metrics', 'backend.utils.async_helpers.tenacity_metrics'),
    ('backend.utils.tenacity_stop', 'backend.utils.async_helpers.tenacity_stop'),
    ('backend.utils.retry', 'backend.utils.async_helpers.retry'),
]

# --- utils/lsp ---

UTILS_LSP_MOVES: dict[str, str] = {
    'lsp_client.py': 'lsp/lsp_client.py',
    'language_tool_aliases.py': 'lsp/language_tool_aliases.py',
}

UTILS_LSP_IMPORTS: list[tuple[str, str]] = [
    ('backend.utils.lsp_client', 'backend.utils.lsp.lsp_client'),
    ('backend.utils.language_tool_aliases', 'backend.utils.lsp.language_tool_aliases'),
]

# --- utils/http ---

UTILS_HTTP_MOVES: dict[str, str] = {
    'http_session.py': 'http/http_session.py',
    'stdio_json_rpc.py': 'http/stdio_json_rpc.py',
}

UTILS_HTTP_IMPORTS: list[tuple[str, str]] = [
    ('backend.utils.http_session', 'backend.utils.http.http_session'),
    ('backend.utils.stdio_json_rpc', 'backend.utils.http.stdio_json_rpc'),
]

# --- utils/terminal ---

UTILS_TERMINAL_MOVES: dict[str, str] = {
    'term_color.py': 'terminal/term_color.py',
    'terminal_contract.py': 'terminal/terminal_contract.py',
}

UTILS_TERMINAL_IMPORTS: list[tuple[str, str]] = [
    ('backend.utils.term_color', 'backend.utils.terminal.term_color'),
    ('backend.utils.terminal_contract', 'backend.utils.terminal.terminal_contract'),
]

# --- orchestration/stuck ---

ORCHESTRATION_STUCK_MOVES: dict[str, str] = {
    'stuck.py': 'stuck/__init__.py',
    'stuck_patterns.py': 'stuck/patterns.py',
}

ORCHESTRATION_STUCK_IMPORTS: list[tuple[str, str]] = [
    ('backend.orchestration.stuck_patterns', 'backend.orchestration.stuck.patterns'),
]

# --- orchestration/agent ---

ORCHESTRATION_AGENT_MOVES: dict[str, str] = {
    'agent.py': 'agent/__init__.py',
    'agent_tools.py': 'agent/tools.py',
    'agent_circuit_breaker.py': 'agent/circuit_breaker.py',
    'autonomy.py': 'agent/autonomy.py',
}

ORCHESTRATION_AGENT_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.orchestration.agent_circuit_breaker',
        'backend.orchestration.agent.circuit_breaker',
    ),
    ('backend.orchestration.agent_tools', 'backend.orchestration.agent.tools'),
    ('backend.orchestration.autonomy', 'backend.orchestration.agent.autonomy'),
]

# --- orchestration/file_edits ---

ORCHESTRATION_FILE_EDITS_MOVES: dict[str, str] = {
    'file_edit_transaction.py': 'file_edits/file_edit_transaction.py',
    'file_state_tracker.py': 'file_edits/file_state_tracker.py',
    'pre_exec_diff.py': 'file_edits/pre_exec_diff.py',
}

ORCHESTRATION_FILE_EDITS_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.orchestration.file_edit_transaction',
        'backend.orchestration.file_edits.file_edit_transaction',
    ),
    (
        'backend.orchestration.file_state_tracker',
        'backend.orchestration.file_edits.file_state_tracker',
    ),
    (
        'backend.orchestration.pre_exec_diff',
        'backend.orchestration.file_edits.pre_exec_diff',
    ),
]

# --- orchestration/telemetry ---

ORCHESTRATION_TELEMETRY_MOVES: dict[str, str] = {
    'tool_telemetry.py': 'telemetry/tool_telemetry.py',
    'conversation_stats.py': 'telemetry/conversation_stats.py',
    'progress_tracker.py': 'telemetry/progress_tracker.py',
}

ORCHESTRATION_TELEMETRY_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.orchestration.tool_telemetry',
        'backend.orchestration.telemetry.tool_telemetry',
    ),
    (
        'backend.orchestration.conversation_stats',
        'backend.orchestration.telemetry.conversation_stats',
    ),
    (
        'backend.orchestration.progress_tracker',
        'backend.orchestration.telemetry.progress_tracker',
    ),
]

# --- orchestration/middleware (root orphans → middleware/) ---

ORCHESTRATION_MIDDLEWARE_MOVES: dict[str, str] = {
    'rollback_middleware.py': 'middleware/rollback_middleware.py',
    'tool_result_validator.py': 'middleware/tool_result_validator.py',
}

ORCHESTRATION_MIDDLEWARE_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.orchestration.rollback_middleware',
        'backend.orchestration.middleware.rollback_middleware',
    ),
    (
        'backend.orchestration.tool_result_validator',
        'backend.orchestration.middleware.tool_result_validator',
    ),
]

# --- execution/utils/git ---

EXECUTION_UTILS_GIT_MOVES: dict[str, str] = {
    'git_common.py': 'git/git_common.py',
    'git_changes.py': 'git/git_changes.py',
    'git_diff.py': 'git/git_diff.py',
    'git_handler.py': 'git/git_handler.py',
}

EXECUTION_UTILS_GIT_IMPORTS: list[tuple[str, str]] = [
    ('backend.execution.utils.git_handler', 'backend.execution.utils.git.git_handler'),
    ('backend.execution.utils.git_changes', 'backend.execution.utils.git.git_changes'),
    ('backend.execution.utils.git_common', 'backend.execution.utils.git.git_common'),
    ('backend.execution.utils.git_diff', 'backend.execution.utils.git.git_diff'),
]

# --- execution/utils/file_editor ---

EXECUTION_UTILS_FILE_EDITOR_MOVES: dict[str, str] = {
    'file_editor.py': 'file_editor/__init__.py',
    '_file_editor_types.py': 'file_editor/_file_editor_types.py',
    '_file_editor_diff_helpers.py': 'file_editor/_file_editor_diff_helpers.py',
    '_file_editor_io_helpers.py': 'file_editor/_file_editor_io_helpers.py',
    '_file_editor_read_write_helpers.py': 'file_editor/_file_editor_read_write_helpers.py',
    '_file_editor_edit_helpers.py': 'file_editor/_file_editor_edit_helpers.py',
    'file_editor_edit_ops.py': 'file_editor/file_editor_edit_ops.py',
    'file_editor_edit_mixin.py': 'file_editor/file_editor_edit_mixin.py',
    'file_editor_ops_mixin.py': 'file_editor/file_editor_ops_mixin.py',
    'file_editor_rollback_mixin.py': 'file_editor/file_editor_rollback_mixin.py',
    'file_editor_view_mixin.py': 'file_editor/file_editor_view_mixin.py',
}

EXECUTION_UTILS_FILE_EDITOR_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.execution.utils._file_editor_read_write_helpers',
        'backend.execution.utils.file_editor._file_editor_read_write_helpers',
    ),
    (
        'backend.execution.utils._file_editor_edit_helpers',
        'backend.execution.utils.file_editor._file_editor_edit_helpers',
    ),
    (
        'backend.execution.utils._file_editor_diff_helpers',
        'backend.execution.utils.file_editor._file_editor_diff_helpers',
    ),
    (
        'backend.execution.utils._file_editor_io_helpers',
        'backend.execution.utils.file_editor._file_editor_io_helpers',
    ),
    (
        'backend.execution.utils._file_editor_types',
        'backend.execution.utils.file_editor._file_editor_types',
    ),
    (
        'backend.execution.utils.file_editor_rollback_mixin',
        'backend.execution.utils.file_editor.file_editor_rollback_mixin',
    ),
    (
        'backend.execution.utils.file_editor_edit_mixin',
        'backend.execution.utils.file_editor.file_editor_edit_mixin',
    ),
    (
        'backend.execution.utils.file_editor_ops_mixin',
        'backend.execution.utils.file_editor.file_editor_ops_mixin',
    ),
    (
        'backend.execution.utils.file_editor_view_mixin',
        'backend.execution.utils.file_editor.file_editor_view_mixin',
    ),
    (
        'backend.execution.utils.file_editor_edit_ops',
        'backend.execution.utils.file_editor.file_editor_edit_ops',
    ),
]

# --- execution/utils/shell ---

EXECUTION_UTILS_SHELL_MOVES: dict[str, str] = {
    'bash.py': 'shell/bash.py',
    'bash_support.py': 'shell/bash_support.py',
    'bash_constants.py': 'shell/bash_constants.py',
    'simple_bash.py': 'shell/simple_bash.py',
    'windows_bash.py': 'shell/windows_bash.py',
    'windows_exceptions.py': 'shell/windows_exceptions.py',
    'unified_shell.py': 'shell/unified_shell.py',
    'pty_session.py': 'shell/pty_session.py',
    'pty_shell_session.py': 'shell/pty_shell_session.py',
    'shell_utils.py': 'shell/shell_utils.py',
    'prompt_detector.py': 'shell/prompt_detector.py',
    'command.py': 'shell/command.py',
    '_bash_command.py': 'shell/_bash_command.py',
    '_bash_detached.py': 'shell/_bash_detached.py',
    '_bash_pane.py': 'shell/_bash_pane.py',
    '_bash_server.py': 'shell/_bash_server.py',
    '_bash_timeouts.py': 'shell/_bash_timeouts.py',
    'session_manager.py': 'shell/session_manager.py',
    'blocking_heuristics.py': 'shell/blocking_heuristics.py',
    'subprocess_background.py': 'shell/subprocess_background.py',
}

EXECUTION_UTILS_SHELL_IMPORTS: list[tuple[str, str]] = [
    (
        'backend.execution.utils.subprocess_background',
        'backend.execution.utils.shell.subprocess_background',
    ),
    (
        'backend.execution.utils.blocking_heuristics',
        'backend.execution.utils.shell.blocking_heuristics',
    ),
    (
        'backend.execution.utils.pty_shell_session',
        'backend.execution.utils.shell.pty_shell_session',
    ),
    (
        'backend.execution.utils.windows_exceptions',
        'backend.execution.utils.shell.windows_exceptions',
    ),
    (
        'backend.execution.utils._bash_timeouts',
        'backend.execution.utils.shell._bash_timeouts',
    ),
    (
        'backend.execution.utils._bash_detached',
        'backend.execution.utils.shell._bash_detached',
    ),
    (
        'backend.execution.utils._bash_command',
        'backend.execution.utils.shell._bash_command',
    ),
    (
        'backend.execution.utils._bash_server',
        'backend.execution.utils.shell._bash_server',
    ),
    (
        'backend.execution.utils.prompt_detector',
        'backend.execution.utils.shell.prompt_detector',
    ),
    (
        'backend.execution.utils.session_manager',
        'backend.execution.utils.shell.session_manager',
    ),
    (
        'backend.execution.utils.unified_shell',
        'backend.execution.utils.shell.unified_shell',
    ),
    (
        'backend.execution.utils.windows_bash',
        'backend.execution.utils.shell.windows_bash',
    ),
    (
        'backend.execution.utils._bash_pane',
        'backend.execution.utils.shell._bash_pane',
    ),
    (
        'backend.execution.utils.bash_constants',
        'backend.execution.utils.shell.bash_constants',
    ),
    (
        'backend.execution.utils.bash_support',
        'backend.execution.utils.shell.bash_support',
    ),
    (
        'backend.execution.utils.simple_bash',
        'backend.execution.utils.shell.simple_bash',
    ),
    (
        'backend.execution.utils.shell_utils',
        'backend.execution.utils.shell.shell_utils',
    ),
    (
        'backend.execution.utils.pty_session',
        'backend.execution.utils.shell.pty_session',
    ),
    ('backend.execution.utils.bash', 'backend.execution.utils.shell.bash'),
    ('backend.execution.utils.command', 'backend.execution.utils.shell.command'),
]

ALL_IMPORTS = (
    CLI_IMPORTS
    + CONTEXT_PIPELINE_IMPORTS
    + CANONICAL_STATE_IMPORTS
    + LLM_IMPORTS
    + PROVIDER_IMPORTS
    + MEMORY_IMPORTS
    + PROCESSORS_IMPORTS
    + COMPACTION_IMPORTS
    + PROMPT_IMPORTS
    + LEDGER_STREAM_IMPORTS
    + LEDGER_INFRA_IMPORTS
    + EXECUTION_RUNTIME_IMPORTS
    + CAPABILITIES_IMPORTS
    + CACHING_IMPORTS
    + EXECUTION_AES_IMPORTS
    + EXECUTION_SERVER_IMPORTS
    + UTILS_TREESITTER_IMPORTS
    + UTILS_ASYNC_HELPERS_IMPORTS
    + UTILS_LSP_IMPORTS
    + UTILS_HTTP_IMPORTS
    + UTILS_TERMINAL_IMPORTS
    + ORCHESTRATION_STUCK_IMPORTS
    + ORCHESTRATION_AGENT_IMPORTS
    + ORCHESTRATION_FILE_EDITS_IMPORTS
    + ORCHESTRATION_TELEMETRY_IMPORTS
    + ORCHESTRATION_MIDDLEWARE_IMPORTS
    + EXECUTION_UTILS_GIT_IMPORTS
    + EXECUTION_UTILS_FILE_EDITOR_IMPORTS
    + EXECUTION_UTILS_SHELL_IMPORTS
)

SKIP_NAMES = {'run_backend_organization.py', 'reorganize_cli_top_level.py'}


def _move_group(base: Path, moves: dict[str, str]) -> None:
    for old, new in moves.items():
        src = base / old
        dst = base / new
        if not src.exists():
            if dst.exists():
                print(f'skip (already moved): {src.relative_to(REPO)}')
                continue
            raise FileNotFoundError(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        print(f'moved {src.relative_to(REPO)} -> {dst.relative_to(REPO)}')


def _write_init(path: Path, doc: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f'"""{doc}"""\n', encoding='utf-8')


def _rewrite_imports() -> None:
    roots = [REPO / 'backend', REPO / 'scripts', REPO / 'docs']
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if path.suffix not in {'.py', '.md'}:
                continue
            if path.name in SKIP_NAMES:
                continue
            text = path.read_text(encoding='utf-8')
            original = text
            for old, new in ALL_IMPORTS:
                text = text.replace(old, new)
            if text != original:
                path.write_text(text, encoding='utf-8')
                print(f'updated imports in {path.relative_to(REPO)}')


def main() -> None:
    _move_group(BACKEND / 'cli', CLI_MOVES)
    _write_init(BACKEND / 'inference' / 'providers' / '__init__.py', 'Direct LLM provider client implementations.')
    _move_group(BACKEND / 'context', CONTEXT_PIPELINE_MOVES)
    _move_group(BACKEND / 'context', CANONICAL_STATE_MOVES)
    _move_group(BACKEND / 'inference', LLM_MOVES)
    _move_group(BACKEND / 'inference', PROVIDER_MOVES)
    _write_init(
        BACKEND / 'context' / 'memory' / '__init__.py',
        'Session, agent, and conversation memory substrates.',
    )
    _move_group(BACKEND / 'context', MEMORY_MOVES)
    _write_init(
        BACKEND / 'context' / 'processors' / '__init__.py',
        'Event action and observation processors for context assembly.',
    )
    _move_group(BACKEND / 'context', PROCESSORS_MOVES)
    _write_init(
        BACKEND / 'context' / 'compaction' / '__init__.py',
        'Compaction boundary, microcompact, and pre-condensation snapshot helpers.',
    )
    _move_group(BACKEND / 'context', COMPACTION_MOVES)
    _write_init(
        BACKEND / 'context' / 'prompt' / '__init__.py',
        'Prompt window selection, assembly, and context packet formatting.',
    )
    _move_group(BACKEND / 'context', PROMPT_MOVES)
    _move_group(BACKEND / 'ledger', LEDGER_STREAM_MOVES)
    _write_init(
        BACKEND / 'ledger' / 'infra' / '__init__.py',
        'Ledger configuration, integrity, masking, and tool-call metadata.',
    )
    _move_group(BACKEND / 'ledger', LEDGER_INFRA_MOVES)
    _write_init(
        BACKEND / 'execution' / 'runtime' / '__init__.py',
        'Runtime pool, factory, orchestrator, and lifecycle manager.',
    )
    _move_group(BACKEND / 'execution', EXECUTION_RUNTIME_MOVES)
    _move_group(BACKEND / 'inference', CAPABILITIES_MOVES)
    _write_init(
        BACKEND / 'inference' / 'caching' / '__init__.py',
        'Prompt cache backends and provider-specific caching helpers.',
    )
    _move_group(BACKEND / 'inference', CACHING_MOVES)
    _write_init(
        BACKEND / 'execution' / 'aes' / '__init__.py',
        'Action execution server helpers — file ops, security, structured edits.',
    )
    _move_group(BACKEND / 'execution', EXECUTION_AES_MOVES)
    _write_init(
        BACKEND / 'execution' / 'server' / '__init__.py',
        'Action execution server HTTP routes and file viewer.',
    )
    _move_group(BACKEND / 'execution', EXECUTION_SERVER_MOVES)
    _write_init(
        BACKEND / 'utils' / 'treesitter' / '__init__.py',
        'Tree-sitter editor, syntax checking, and chunk localization.',
    )
    _move_group(BACKEND / 'utils', UTILS_TREESITTER_MOVES)
    _write_init(
        BACKEND / 'utils' / 'async_helpers' / '__init__.py',
        'Async/sync bridging, retries, circuit breakers, and subprocess helpers.',
    )
    _move_group(BACKEND / 'utils', UTILS_ASYNC_HELPERS_MOVES)
    _write_init(
        BACKEND / 'utils' / 'lsp' / '__init__.py',
        'LSP client wrapper and language-server name aliases.',
    )
    _move_group(BACKEND / 'utils', UTILS_LSP_MOVES)
    _write_init(
        BACKEND / 'utils' / 'http' / '__init__.py',
        'HTTP session wrapper and stdio JSON-RPC framing helpers.',
    )
    _move_group(BACKEND / 'utils', UTILS_HTTP_MOVES)
    _write_init(
        BACKEND / 'utils' / 'terminal' / '__init__.py',
        'Terminal color helpers and shell/tool-registry contract adapters.',
    )
    _move_group(BACKEND / 'utils', UTILS_TERMINAL_MOVES)
    _move_group(BACKEND / 'orchestration', ORCHESTRATION_STUCK_MOVES)
    _move_group(BACKEND / 'orchestration', ORCHESTRATION_AGENT_MOVES)
    _write_init(
        BACKEND / 'orchestration' / 'file_edits' / '__init__.py',
        'File edit transactions, state tracking, and pre-exec diff middleware.',
    )
    _move_group(BACKEND / 'orchestration', ORCHESTRATION_FILE_EDITS_MOVES)
    _write_init(
        BACKEND / 'orchestration' / 'telemetry' / '__init__.py',
        'Tool telemetry, conversation stats, and progress tracking.',
    )
    _move_group(BACKEND / 'orchestration', ORCHESTRATION_TELEMETRY_MOVES)
    _move_group(BACKEND / 'orchestration', ORCHESTRATION_MIDDLEWARE_MOVES)
    _write_init(
        BACKEND / 'execution' / 'utils' / 'git' / '__init__.py',
        'Git diff, change parsing, and command helpers for the runtime.',
    )
    _move_group(BACKEND / 'execution' / 'utils', EXECUTION_UTILS_GIT_MOVES)
    _move_group(BACKEND / 'execution' / 'utils', EXECUTION_UTILS_FILE_EDITOR_MOVES)
    _write_init(
        BACKEND / 'execution' / 'utils' / 'shell' / '__init__.py',
        'Shell sessions — bash, PTY, Windows PowerShell, and session management.',
    )
    _move_group(BACKEND / 'execution' / 'utils', EXECUTION_UTILS_SHELL_MOVES)
    _rewrite_imports()
    print('backend organization complete')


if __name__ == '__main__':
    main()
