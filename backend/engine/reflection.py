from typing import Any
from backend.orchestration.state.state import State
from backend.ledger.action import MessageAction, AgentThinkAction

def format_reflection_progress(state: State) -> str:
    """Format progress line from iteration_flag."""
    iter_flag = getattr(state, "iteration_flag", None)
    current = getattr(iter_flag, "current_value", 0) if iter_flag else 0
    max_val = getattr(iter_flag, "max_value", 0) if iter_flag else 0
    if not current:
        return ""
    progress = f"Turn {current}"
    if max_val:
        progress += f"/{max_val} ({int(current / max_val * 100)}% of budget)"
    return f"  • Progress: {progress}"

def format_reflection_metrics(state: State) -> list[str]:
    """Format context usage and cost lines from metrics."""
    parts: list[str] = []
    metrics = getattr(state, "metrics", None)
    if not metrics:
        return parts
    atu = getattr(metrics, "accumulated_token_usage", None)
    if atu:
        prompt_tok = getattr(atu, "prompt_tokens", 0)
        ctx_window = getattr(atu, "context_window", 0)
        if prompt_tok and ctx_window:
            pct = int(prompt_tok / ctx_window * 100)
            parts.append(f"  • Context usage: {pct}% ({prompt_tok}/{ctx_window} tokens)")
    cost = getattr(metrics, "accumulated_cost", 0.0)
    if cost > 0:
        parts.append(f"  • Cost so far: ${cost:.4f}")
    return parts

def format_reflection_modified_files(modified_files: list[str]) -> str:
    """Format modified files line."""
    if not modified_files:
        return ""
    files_str = ", ".join(modified_files[-5:])
    if len(modified_files) > 5:
        files_str += f" (+{len(modified_files) - 5} more)"
    return f"  • Files modified: {files_str}"

def format_reflection_initial_request(
    memory_manager: Any, history: list
) -> str:
    """Format original request line from initial user message."""
    try:
        initial_msg = memory_manager.get_initial_user_message(history)
        task_text = getattr(initial_msg, "content", "")[:200]
        return f'  • Original request: "{task_text}"' if task_text else ""
    except Exception:
        return ""

def build_reflection_data_parts(
    state: State,
    memory_manager: Any,
    modified_files: list[str],
) -> list[str]:
    parts = []
    
    initial_req = format_reflection_initial_request(memory_manager, state.history)
    if initial_req:
        parts.append(initial_req)
        
    prog = format_reflection_progress(state)
    if prog:
        parts.append(prog)
        
    parts.extend(format_reflection_metrics(state))
    
    mod_files = format_reflection_modified_files(modified_files)
    if mod_files:
        parts.append(mod_files)
        
    if not parts:
        parts.append("  • (No data available)")
    return parts
