"""Status, cost, health, and autonomy handlers for :class:`SlashCommandsMixin`.

Read-only inspection commands and the autonomy level toggle.
"""

from __future__ import annotations

from typing import Any


def _circuit_breaker_diag(controller: Any) -> str:
    breaker_state = 'n/a'
    consecutive_errors: int | str = 'n/a'
    error_rate: float | str = 'n/a'
    if controller is not None:
        breaker = getattr(controller, 'circuit_breaker', None)
        if breaker is not None:
            consecutive_errors = getattr(breaker, 'consecutive_errors', 'n/a')
            try:
                error_rate = round(float(breaker._calculate_error_rate()), 3)
            except Exception:
                error_rate = 'n/a'
            breaker_state = (
                'tripped'
                if isinstance(consecutive_errors, int)
                and consecutive_errors
                >= getattr(
                    getattr(breaker, 'config', None),
                    'max_consecutive_errors',
                    10**9,
                )
                else 'closed'
            )
    return (
        f'  circuit_breaker: state={breaker_state} '
        f'consecutive_errors={consecutive_errors} error_rate={error_rate}'
    )


def _event_stream_depth(controller: Any) -> str:
    depth: int | str = 'n/a'
    if controller is not None:
        stream = getattr(controller, 'event_stream', None) or getattr(
            controller, '_event_stream', None
        )
        if stream is not None:
            queue = getattr(stream, '_queue', None)
            if queue is not None:
                try:
                    depth = queue.qsize()
                except Exception:
                    depth = 'n/a'
    return f'  event_stream_queue_depth: {depth}'


def _checkpoint_count(controller: Any) -> str:
    count: int | str = 'n/a'
    if controller is not None:
        ckpt_mgr = getattr(controller, 'checkpoint_manager', None)
        if ckpt_mgr is not None:
            checkpoints = getattr(ckpt_mgr, 'checkpoints', None) or getattr(
                ckpt_mgr, '_checkpoints', None
            )
            try:
                if checkpoints is not None:
                    count = len(checkpoints)
            except Exception:
                count = 'n/a'
    return f'  checkpoints: {count}'


def _condensation_count(controller: Any) -> str:
    count: int | str = 'n/a'
    if controller is not None:
        monitor = getattr(controller, 'memory_pressure', None)
        if monitor is not None:
            count = monitor._condensation_count
    return f'  condensation_events: {count}'


def _cost_line(host: Any) -> str:
    hud = host._hud.state
    return (
        f'  cost: ${hud.cost_usd:.4f} ({hud.context_tokens:,} ctx tokens, '
        f'{hud.llm_calls} LLM calls)'
    )


def _tracing_line() -> str:
    import os

    tracing_optout = any(
        os.getenv(var, '').strip().lower() in ('1', 'true', 'yes', 'on')
        for var in ('DO_NOT_TRACK', 'GRINTA_DISABLE_METRICS')
    )
    tracing_enabled_env = (
        os.getenv('TRACING_ENABLED', 'true').lower() == 'true' and not tracing_optout
    )
    return f'  tracing: enabled={tracing_enabled_env} opt_out_env={tracing_optout}'


def build_status_diagnostics(host: Any) -> str:
    """Best-effort runtime diagnostics for ``/status verbose``.

    All attribute accesses are wrapped — if any subsystem isn't wired up
    yet (no active controller, no breaker, etc.) the line is shown as
    ``n/a`` rather than raising.
    """
    controller = host._controller
    lines: list[str] = ['Diagnostics:']
    lines.append(_circuit_breaker_diag(controller))
    lines.append(_event_stream_depth(controller))
    lines.append(_checkpoint_count(controller))
    lines.append(_condensation_count(controller))
    lines.append(_cost_line(host))
    lines.append(_tracing_line())
    return '\n'.join(lines)


def cmd_status(host: Any, parsed: Any) -> bool:
    verbose = False
    if parsed.args:
        arg = parsed.args[0].strip().lower()
        if arg in ('-v', '--verbose', 'verbose', 'v', 'full'):
            verbose = True
        else:
            host._warn(f'Usage: {host._usage(parsed.name)}')
            return True
        if len(parsed.args) > 1:
            host._warn(f'Usage: {host._usage(parsed.name)}')
            return True
    if host._renderer is None:
        return True
    body = host._hud.plain_text()
    if verbose:
        body = body + '\n\n' + build_status_diagnostics(host)
    host._renderer.add_system_message(body, title='status')
    return True


def cmd_cost(host: Any, parsed: Any) -> bool:
    if host._reject_extra_args(parsed):
        return True
    hud = host._hud.state
    tokens = (
        f'{hud.context_tokens:,} ctx · {hud.llm_calls} LLM calls'
        if hud.llm_calls
        else 'no LLM calls yet'
    )
    msg = f'Session cost: ${hud.cost_usd:.4f}  ·  {tokens}\nModel: {hud.model}'
    if host._renderer is not None:
        host._renderer.add_system_message(msg, title='cost')
    return True


def cmd_health(host: Any, parsed: Any) -> bool:
    """Run a fast self-check.

    Verifies provider reachable, debugpy importable, ripgrep + git
    available.
    """
    if host._reject_extra_args(parsed):
        return True
    import shutil

    checks: list[tuple[str, bool, str]] = []

    try:
        import importlib

        importlib.import_module('debugpy.adapter')
        checks.append(('debugpy', True, 'importable'))
    except Exception as exc:
        checks.append(('debugpy', False, f'import failed: {exc}'))

    for binary in ('rg', 'git'):
        path = shutil.which(binary)
        checks.append((binary, path is not None, path or 'not found on PATH'))

    hud = host._hud.state
    checks.append(('model', bool(hud.model), hud.model or 'not set'))

    lines = ['Self-check:']
    for name, ok, detail in checks:
        mark = 'ok ' if ok else 'FAIL'
        lines.append(f'  [{mark}] {name}: {detail}')

    if host._renderer is not None:
        host._renderer.add_system_message('\n'.join(lines), title='health')
    return True


def get_current_autonomy(host: Any) -> str:
    controller = host._controller
    if controller is not None:
        ac = getattr(controller, 'autonomy_controller', None)
        if ac is not None:
            return str(getattr(ac, 'autonomy_level', 'balanced'))
    return 'balanced (default)'


def show_current_autonomy(host: Any, valid_levels: tuple[str, ...]) -> None:
    from backend.cli.repl.slash_command_registry import _AUTONOMY_LEVEL_HINTS

    level = get_current_autonomy(host)
    if host._renderer is None:
        return
    level_lines = '\n'.join(
        f'  {name:<10} — {_AUTONOMY_LEVEL_HINTS[name]}' for name in valid_levels
    )
    host._renderer.add_system_message(
        f'Autonomy: {level}\n'
        f'{level_lines}\n'
        f'Change with: /autonomy <{"|".join(valid_levels)}>',
        title='autonomy',
    )


def _host_active_agent_name(host: Any) -> str:
    from backend.core.constants import DEFAULT_AGENT_NAME

    config = getattr(host, '_config', None)
    if config is None:
        return DEFAULT_AGENT_NAME
    name = getattr(config, 'default_agent', None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    return DEFAULT_AGENT_NAME


def apply_autonomy_level(host: Any, new_level: str) -> None:
    from backend.cli.settings import get_persisted_autonomy_level, update_autonomy_level

    agent_name = _host_active_agent_name(host)
    if new_level == get_persisted_autonomy_level(agent_name):
        controller = host._controller
        if controller is not None:
            ac = getattr(controller, 'autonomy_controller', None)
            if ac is not None and getattr(ac, 'autonomy_level', None) == new_level:
                return

    controller = host._controller
    if controller is not None:
        ac = getattr(controller, 'autonomy_controller', None)
        if ac is not None:
            previous = getattr(ac, 'autonomy_level', None)
            ac.autonomy_level = new_level
            if previous != new_level:
                update_autonomy_level(new_level, agent_name)
            if host._renderer is not None:
                host._renderer.add_system_message(
                    f'Autonomy set to: {new_level}', title='autonomy'
                )
            return
    if host._renderer is not None:
        host._renderer.add_system_message(
            'No active controller. Send a message first to initialize, then set autonomy.',
            title='warning',
        )


def handle_autonomy_command(host: Any, parsed: Any) -> None:
    """View or change the autonomy level."""
    from backend.cli.repl.slash_command_registry import _AUTONOMY_LEVEL_HINTS

    valid_levels = tuple(_AUTONOMY_LEVEL_HINTS)

    if not parsed.args:
        show_current_autonomy(host, valid_levels)
        return

    if len(parsed.args) > 1:
        host._warn(f'Usage: {host._usage(parsed.name)}')
        return

    new_level = parsed.args[0].lower()
    if new_level not in valid_levels:
        if host._renderer is not None:
            host._renderer.add_system_message(
                f"Invalid level '{new_level}'. Use: {', '.join(valid_levels)}",
                title='warning',
            )
        return

    apply_autonomy_level(host, new_level)


def cmd_autonomy(host: Any, parsed: Any) -> bool:
    handle_autonomy_command(host, parsed)
    return True
