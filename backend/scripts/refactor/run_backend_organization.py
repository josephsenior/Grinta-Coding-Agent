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
    _rewrite_imports()
    print('backend organization complete')


if __name__ == '__main__':
    main()
