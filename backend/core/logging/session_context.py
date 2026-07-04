"""Runtime context snapshot attached to session.jsonl events."""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

_LOCK = threading.Lock()
_CONTROLLER: Any | None = None
_LLM_CONFIG: Any | None = None
_LAST_FULL_SNAPSHOT: dict[str, Any] | None = None
_LAST_CTX_HASH: str | None = None


def register_runtime_context(
    controller: Any | None = None,
    llm_config: Any | None = None,
) -> None:
    """Register live controller / LLM config for context snapshots."""
    global _CONTROLLER, _LLM_CONFIG
    with _LOCK:
        if controller is not None:
            _CONTROLLER = controller
        if llm_config is not None:
            _LLM_CONFIG = llm_config


def clear_runtime_context() -> None:
    global _CONTROLLER, _LLM_CONFIG, _LAST_FULL_SNAPSHOT, _LAST_CTX_HASH
    with _LOCK:
        _CONTROLLER = None
        _LLM_CONFIG = None
        _LAST_FULL_SNAPSHOT = None
        _LAST_CTX_HASH = None


def _compact_llm_config(config: Any) -> dict[str, Any]:
    return {
        'temperature': getattr(config, 'temperature', None),
        'top_p': getattr(config, 'top_p', None),
        'top_k': getattr(config, 'top_k', None),
        'reasoning_effort': getattr(config, 'reasoning_effort', None),
        'native_tool_calling': getattr(config, 'native_tool_calling', None),
        'context_window_tokens': getattr(config, 'context_window_tokens', None),
        'max_output_tokens': getattr(config, 'max_output_tokens', None),
        'prompt_history_token_budget': getattr(
            config, 'prompt_history_token_budget', None
        ),
        'prompt_history_budget_ratio': getattr(
            config, 'prompt_history_budget_ratio', None
        ),
        'prompt_history_max_events': getattr(config, 'prompt_history_max_events', None),
    }


def capture_context_snapshot() -> dict[str, Any]:
    """Return compact ctx dict for session.jsonl envelope."""
    controller = _CONTROLLER
    llm_config = _LLM_CONFIG
    mode = None
    active_run_mode = None
    autonomy = None

    if controller is not None:
        agent = getattr(controller, 'agent', None)
        config = getattr(agent, 'config', None) if agent is not None else None
        if config is not None:
            mode = getattr(config, 'mode', None)
            autonomy = getattr(config, 'autonomy_level', None)
        state = getattr(controller, 'state', None)
        extra = getattr(state, 'extra_data', None) if state is not None else None
        if isinstance(extra, dict):
            active_run_mode = extra.get('active_run_mode')
        autonomy_ctrl = getattr(controller, 'autonomy_controller', None)
        if autonomy_ctrl is not None:
            autonomy = getattr(autonomy_ctrl, 'autonomy_level', autonomy)

    model = None
    provider = None
    reasoning_effort = None
    llm_config_block: dict[str, Any] = {}

    if llm_config is not None:
        model = getattr(llm_config, 'model', None)
        provider = getattr(llm_config, 'custom_llm_provider', None)
        reasoning_effort = getattr(llm_config, 'reasoning_effort', None)
        llm_config_block = _compact_llm_config(llm_config)
        try:
            from backend.inference.llm.config import _llm_model_metadata_for_log
            from backend.inference.provider_resolver import get_resolver

            meta = _llm_model_metadata_for_log(llm_config, get_resolver())
            model = meta.get('model', model)
            provider = meta.get('resolved_provider', provider)
            cfg_params = meta.get('config_params')
            if isinstance(cfg_params, dict):
                reasoning_effort = cfg_params.get('reasoning_effort', reasoning_effort)
                llm_config_block = {**llm_config_block, **cfg_params}
        except Exception:
            pass

    astep = None
    try:
        from backend.core.prompt_role_debug import current_astep_id

        astep = current_astep_id()
    except Exception:
        pass
    return {
        'mode': mode,
        'active_run_mode': active_run_mode,
        'autonomy': autonomy,
        'model': model,
        'provider': provider,
        'reasoning_effort': reasoning_effort,
        'llm_config': llm_config_block,
        'astep_id': astep if astep else None,
    }


def capture_full_session_context() -> dict[str, Any]:
    """Full snapshot for SESSION_CONTEXT events."""
    ctx = capture_context_snapshot()
    extra: dict[str, Any] = {}
    llm_config = _LLM_CONFIG
    if llm_config is not None:
        try:
            from backend.inference.llm.config import _llm_model_metadata_for_log
            from backend.inference.provider_resolver import get_resolver

            extra['llm_metadata'] = _llm_model_metadata_for_log(
                llm_config, get_resolver()
            )
        except Exception:
            pass
    return {**ctx, **extra}


def context_hash(snapshot: dict[str, Any]) -> str:
    """Hash context for change detection (exclude astep_id)."""
    stable = {k: v for k, v in snapshot.items() if k != 'astep_id'}
    raw = json.dumps(stable, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def consume_context_change() -> dict[str, Any] | None:
    """If context changed since last check, return full snapshot for SESSION_CONTEXT."""
    global _LAST_FULL_SNAPSHOT, _LAST_CTX_HASH
    full = capture_full_session_context()
    h = context_hash(full)
    with _LOCK:
        if h == _LAST_CTX_HASH:
            return None
        _LAST_CTX_HASH = h
        _LAST_FULL_SNAPSHOT = full
        return dict(full)
