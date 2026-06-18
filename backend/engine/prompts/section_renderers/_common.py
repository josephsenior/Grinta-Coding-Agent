"""Cross-cutting helpers used by multiple section renderers."""

from __future__ import annotations

from backend.inference.capabilities.provider_capabilities import (
    model_token_correction as _model_token_correction,
)


def _count_section_tokens(text: str, model_id: str) -> tuple[int, str]:
    """Best-effort token count for budgeting. Returns (tokens, encoding_label)."""
    try:
        import tiktoken  # type: ignore

        mid = (model_id or '').strip().lower()

        if mid:
            try:
                enc = tiktoken.encoding_for_model(mid)
                tokens = len(enc.encode(text))
                return tokens, f'model:{mid}'
            except Exception:
                pass

        enc = tiktoken.get_encoding('o200k_base')
        tokens = len(enc.encode(text))
        factor, label = _model_token_correction(model_id)
        if factor != 1.0:
            tokens = int(tokens * factor)
        return tokens, label
    except Exception:
        est = max(0, len(text) // 4)
        return est, 'chars_div_4_fallback'


def _choose(is_windows: bool, win: str, unix: str) -> str:
    return win if is_windows else unix


def _resolve_terminal_command_tool(
    is_windows: bool,
    terminal_tool_name: str | None,
) -> str:
    """Resolve the active terminal command tool for prompt rendering."""
    if terminal_tool_name:
        return terminal_tool_name
    return 'execute_powershell' if is_windows else 'execute_bash'
