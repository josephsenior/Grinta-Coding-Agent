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
    """Run a fast self-check using the shared doctor check registry."""
    if host._reject_extra_args(parsed):
        return True
    from backend.cli.doctor.checks import (
        collect_health_checks,
        format_health_report_lines,
    )

    model_hint = getattr(host._hud.state, 'model', None)
    checks = collect_health_checks(model_hint=model_hint)
    lines = format_health_report_lines(checks)
    lines.append('  For a fuller report, run `grinta doctor` outside the session.')

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
    from backend.cli.repl.slash_registry_commands import _AUTONOMY_LEVEL_HINTS

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
    persisted = get_persisted_autonomy_level(agent_name)
    controller = host._controller
    ac = (
        getattr(controller, 'autonomy_controller', None)
        if controller is not None
        else None
    )
    if (
        new_level == persisted
        and ac is not None
        and getattr(ac, 'autonomy_level', None) == new_level
    ):
        return

    if new_level != persisted:
        update_autonomy_level(new_level, agent_name)

    if controller is not None and ac is not None:
        ac.autonomy_level = new_level
        config = getattr(host, '_config', None)
        if config is not None:
            try:
                agent_config = config.get_agent_config(agent_name)
                agent_config.autonomy_level = new_level
                setattr(config, 'autonomy_level', new_level)
            except Exception:
                pass
        hud = getattr(host, '_hud', None)
        if hud is not None and hasattr(hud, 'update_autonomy'):
            hud.update_autonomy(new_level)
        if host._renderer is not None:
            host._renderer.add_system_message(
                f'Autonomy set to: {new_level}', title='autonomy'
            )
        return
    if host._renderer is not None:
        host._renderer.add_system_message(
            f'Autonomy set to: {new_level} (saved; applies on next session)',
            title='autonomy',
        )


def handle_autonomy_command(host: Any, parsed: Any) -> None:
    """View or change the autonomy level."""
    from backend.cli.repl.slash_registry_commands import _AUTONOMY_LEVEL_HINTS

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


def _host_active_run_mode(host: Any) -> object:
    controller = getattr(host, '_controller', None)
    if controller is None:
        return None
    state = getattr(controller, 'state', None)
    if state is None:
        return None
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return None
    return extra.get('active_run_mode')


def get_current_interaction_mode(host: Any) -> str:
    from backend.core.interaction_modes import (
        resolve_active_interaction_mode,
    )

    configured_mode: object = None
    controller = host._controller
    if controller is not None:
        agent = getattr(controller, 'agent', None)
        running_config = getattr(agent, 'config', None) if agent is not None else None
        if running_config is not None:
            configured_mode = getattr(running_config, 'mode', None)
    if configured_mode is None:
        config = getattr(host, '_config', None)
        if config is not None:
            try:
                agent_name = _host_active_agent_name(host)
                agent_config = config.get_agent_config(agent_name)
                configured_mode = getattr(agent_config, 'mode', None)
            except Exception:
                pass
    if configured_mode is None:
        from backend.cli.settings import get_persisted_interaction_mode

        persisted = get_persisted_interaction_mode(_host_active_agent_name(host))
        if persisted:
            configured_mode = persisted
    return resolve_active_interaction_mode(
        active_run_mode=_host_active_run_mode(host),
        configured_mode=configured_mode or 'agent',
    )


def show_current_interaction_mode(host: Any, valid_modes: tuple[str, ...]) -> None:
    from backend.cli.repl.slash_registry_commands import _INTERACTION_MODE_HINTS

    mode = get_current_interaction_mode(host)
    if host._renderer is None:
        return
    mode_lines = '\n'.join(
        f'  {name:<6} — {_INTERACTION_MODE_HINTS[name]}' for name in valid_modes
    )
    host._renderer.add_system_message(
        f'Mode: {mode}\n{mode_lines}\nChange with: /mode <{"|".join(valid_modes)}>',
        title='mode',
    )


def apply_interaction_mode(host: Any, new_mode: str) -> None:
    from backend.cli.settings import (
        get_persisted_interaction_mode,
        update_interaction_mode,
    )
    from backend.cli.settings.mode_runtime import apply_interaction_mode_to_controller
    from backend.core.interaction_modes import (
        VISIBLE_INTERACTION_MODES,
        normalize_interaction_mode,
    )

    mode = normalize_interaction_mode(new_mode)
    if mode not in VISIBLE_INTERACTION_MODES:
        return

    apply_mode_hook = getattr(host, '_apply_mode', None)
    if callable(apply_mode_hook):
        apply_mode_hook(mode)
        return

    agent_name = _host_active_agent_name(host)
    if mode == get_persisted_interaction_mode(agent_name):
        controller = host._controller
        if controller is not None:
            agent = getattr(controller, 'agent', None)
            running_config = (
                getattr(agent, 'config', None) if agent is not None else None
            )
            if (
                running_config is not None
                and normalize_interaction_mode(getattr(running_config, 'mode', None))
                == mode
            ):
                return

    config = getattr(host, '_config', None)
    if config is not None:
        try:
            agent_config = config.get_agent_config(agent_name)
            agent_config.mode = mode
        except Exception:
            pass

    controller = getattr(host, '_controller', None)
    if controller is not None:
        apply_interaction_mode_to_controller(controller, mode)

    update_interaction_mode(mode, agent_name)
    hud = getattr(host, '_hud', None)
    if hud is not None and hasattr(hud, 'update_interaction_mode'):
        hud.update_interaction_mode(mode)
    if host._renderer is not None:
        host._renderer.add_system_message(f'Mode set to: {mode}', title='mode')


def handle_interaction_mode_command(host: Any, parsed: Any) -> None:
    from backend.cli.repl.slash_registry_commands import _INTERACTION_MODE_HINTS

    valid_modes = tuple(_INTERACTION_MODE_HINTS)

    if not parsed.args:
        show_current_interaction_mode(host, valid_modes)
        return

    if len(parsed.args) > 1:
        host._warn(f'Usage: {host._usage(parsed.name)}')
        return

    new_mode = parsed.args[0].lower()
    if new_mode not in valid_modes:
        if host._renderer is not None:
            host._renderer.add_system_message(
                f"Invalid mode '{new_mode}'. Use: {', '.join(valid_modes)}",
                title='warning',
            )
        return

    apply_interaction_mode(host, new_mode)


def cmd_mode(host: Any, parsed: Any) -> bool:
    handle_interaction_mode_command(host, parsed)
    return True
