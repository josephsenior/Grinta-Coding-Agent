"""Standalone diagnostics for ``grinta doctor``.

Aggregates environment, configuration, toolchain, and sandbox checks so users
can debug install issues without starting the interactive REPL.
"""

from __future__ import annotations

import importlib
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from backend.cli.theme import (
    CLR_CARD_BORDER,
    CLR_CARD_TITLE,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    STYLE_DIM,
    mark_err,
    mark_ok,
    mark_warn,
    use_ascii_cli_symbols,
)


@dataclass(frozen=True)
class DoctorCheck:
    """One row in the doctor report."""

    name: str
    ok: bool
    detail: str
    critical: bool = True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _check_version() -> DoctorCheck:
    try:
        from backend import get_version

        version = get_version()
    except Exception as exc:
        return DoctorCheck('version', False, f'unavailable: {exc}')
    return DoctorCheck('version', True, version, critical=False)


def _check_python() -> DoctorCheck:
    return DoctorCheck(
        'python',
        True,
        f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
        critical=False,
    )


def _check_platform() -> DoctorCheck:
    from backend.core.os_capabilities import OS_CAPS

    sep = ' · ' if _stdout_supports_unicode() else ' - '
    name = platform.system()
    detail = f'{name} ({sys.platform})'
    if OS_CAPS.is_linux:
        detail += f'{sep}linux'
    elif OS_CAPS.is_windows:
        detail += f'{sep}windows'
    elif OS_CAPS.is_macos:
        detail += f'{sep}macos'
    return DoctorCheck('platform', True, detail, critical=False)


def _check_settings_file() -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path

    path = Path(get_canonical_settings_path())
    if not path.is_file():
        return DoctorCheck(
            'settings',
            False,
            f'missing: {path} (run `grinta init` or copy settings.template.json)',
        )
    return DoctorCheck('settings', True, str(path))


def _check_settings_schema() -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path
    from backend.core.config import AppConfig
    from backend.core.config.config_loader import load_from_json
    from backend.core.constants import DEFAULT_AGENT_NAME

    path = get_canonical_settings_path()
    if not Path(path).is_file():
        return DoctorCheck('settings_schema', False, 'settings.json not found', critical=False)

    try:
        cfg = AppConfig()
        load_from_json(cfg, path)
    except Exception as exc:
        return DoctorCheck('settings_schema', False, f'load failed: {exc}')

    import json

    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    agent_overrides = raw.get('agent')
    if isinstance(agent_overrides, dict) and 'agent' in agent_overrides:
        return DoctorCheck(
            'settings_schema',
            False,
            'nested agent.agent override detected; use agent.Orchestrator instead',
            critical=False,
        )

    orchestrator = cfg.get_agent_config(DEFAULT_AGENT_NAME)
    profile = cfg.security.execution_profile
    return DoctorCheck(
        'settings_schema',
        True,
        f'agent={DEFAULT_AGENT_NAME} autonomy={orchestrator.autonomy_level} profile={profile}',
        critical=False,
    )


def _check_llm_config() -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path
    from backend.core.config import AppConfig
    from backend.core.config.api_key_manager import api_key_manager
    from backend.core.config.config_loader import load_from_json

    path = get_canonical_settings_path()
    if not Path(path).is_file():
        return DoctorCheck('llm', False, 'settings.json not found')

    try:
        cfg = AppConfig()
        with api_key_manager.suppress_env_export_context():
            load_from_json(cfg, path)
        llm_cfg = cfg.get_llm_config()
    except Exception as exc:
        return DoctorCheck('llm', False, f'config load failed: {exc}')

    model = (llm_cfg.model or '').strip()
    if not model:
        return DoctorCheck(
            'llm',
            False,
            'llm_model not set (run `grinta init` or edit settings.json)',
        )

    key = api_key_manager.get_api_key_for_model(model, llm_cfg.api_key)
    if key is None or not key.get_secret_value().strip():
        return DoctorCheck(
            'llm',
            False,
            f'model={model} but no API key resolved (set LLM_API_KEY or provider env var)',
        )

    provider = api_key_manager.extract_provider(model)
    return DoctorCheck('llm', True, f'provider={provider} model={model} key=resolved')


def _check_execution_profile() -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path
    from backend.core.config import AppConfig
    from backend.core.config.config_loader import load_from_json
    from backend.execution.sandboxing import resolve_execution_sandbox_policy

    path = get_canonical_settings_path()
    if not Path(path).is_file():
        return DoctorCheck('execution', False, 'settings.json not found', critical=False)

    try:
        cfg = AppConfig()
        load_from_json(cfg, path)
    except Exception as exc:
        return DoctorCheck('execution', False, f'load failed: {exc}', critical=False)

    profile = cfg.security.execution_profile
    if profile != 'sandboxed_local':
        return DoctorCheck('execution', True, f'profile={profile}', critical=False)

    try:
        policy = resolve_execution_sandbox_policy(
            security_config=cfg.security,
            workspace_root=Path.cwd(),
        )
    except RuntimeError as exc:
        return DoctorCheck('execution', False, str(exc), critical=False)

    backend = policy.backend if policy is not None else 'disabled'
    return DoctorCheck(
        'execution',
        True,
        f'profile={profile} backend={backend}',
        critical=False,
    )


def _check_binary(name: str, *, critical: bool = True) -> DoctorCheck:
    path = shutil.which(name)
    if path:
        return DoctorCheck(name, True, path, critical=critical)
    return DoctorCheck(name, False, 'not found on PATH', critical=critical)


def _check_debugpy() -> DoctorCheck:
    try:
        importlib.import_module('debugpy.adapter')
    except Exception as exc:
        return DoctorCheck(
            'debugpy',
            False,
            f'not installed (optional): {exc}',
            critical=False,
        )
    return DoctorCheck('debugpy', True, 'importable', critical=False)


def _check_optional_imports() -> DoctorCheck:
    script = _repo_root() / 'backend' / 'scripts' / 'verify' / 'verify_optional_imports.py'
    if not script.is_file():
        return DoctorCheck(
            'optional_imports',
            False,
            f'verify script missing: {script}',
            critical=False,
        )
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    if proc.returncode == 0:
        return DoctorCheck('optional_imports', True, 'no top-level optional import leaks', critical=False)
    detail = (proc.stderr or proc.stdout or 'failed').strip().splitlines()
    first = detail[0] if detail else 'failed'
    return DoctorCheck('optional_imports', False, first, critical=False)


def _check_editing_stack() -> DoctorCheck:
    from backend.engine.tools.health_check import run_production_health_check

    try:
        result = run_production_health_check(raise_on_failure=False)
    except Exception as exc:
        return DoctorCheck('editing_stack', False, str(exc), critical=False)

    overall = result.get('overall_status', 'UNKNOWN')
    if overall == 'HEALTHY':
        return DoctorCheck('editing_stack', True, 'structure editor + atomic refactor', critical=False)
    se = result.get('structure_editor', {})
    msg = se.get('message', overall) if isinstance(se, dict) else overall
    return DoctorCheck('editing_stack', False, str(msg), critical=False)


def collect_checks(*, verbose: bool = False) -> list[DoctorCheck]:
    """Run all doctor checks and return structured results."""
    checks: list[DoctorCheck] = [
        _check_version(),
        _check_python(),
        _check_platform(),
        _check_settings_file(),
        _check_settings_schema(),
        _check_llm_config(),
        _check_execution_profile(),
        _check_binary('git'),
        _check_binary('rg'),
        _check_debugpy(),
        _check_optional_imports(),
    ]
    if verbose:
        checks.append(_check_editing_stack())
    return checks


def _stdout_supports_unicode() -> bool:
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        '\u2713'.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _status_mark(check: DoctorCheck) -> str:
    if not _stdout_supports_unicode() and not use_ascii_cli_symbols():
        if check.ok:
            return '+'
        if check.critical:
            return 'x'
        return '!'
    if check.ok:
        return mark_ok()
    if check.critical:
        return mark_err()
    return mark_warn()


def _render_report(console: Console, checks: list[DoctorCheck]) -> None:
    table = Table(
        box=None,
        show_header=True,
        header_style=STYLE_DIM,
        border_style=CLR_CARD_BORDER,
        title=f'[{CLR_CARD_TITLE}]Grinta doctor[/]',
        title_style='',
    )
    table.add_column('Status', width=6, no_wrap=True)
    table.add_column('Check', style='bold', no_wrap=True)
    table.add_column('Detail', overflow='fold')

    for check in checks:
        mark = _status_mark(check)
        status_style = CLR_STATUS_OK if check.ok else (
            CLR_STATUS_ERR if check.critical else CLR_STATUS_WARN
        )
        table.add_row(
            f'[{status_style}]{mark}[/]',
            check.name,
            check.detail,
        )

    console.print(table)

    critical_failures = [c for c in checks if c.critical and not c.ok]
    warnings = [c for c in checks if not c.critical and not c.ok]
    if critical_failures:
        console.print(
            f'\n[{CLR_STATUS_ERR}]'
            f'{len(critical_failures)} critical check(s) failed. '
            'Fix the items above before running tasks.[/]'
        )
    elif warnings:
        console.print(
            f'\n[{CLR_STATUS_WARN}]'
            f'{len(warnings)} optional check(s) need attention.[/]'
        )
    else:
        console.print(f'\n[{CLR_STATUS_OK}]All checks passed.[/]')


def cmd_doctor(console: Console, *, verbose: bool = False) -> int:
    """Run diagnostics and print a report. Returns a process exit code."""
    checks = collect_checks(verbose=verbose)
    _render_report(console, checks)
    if any(not check.ok and check.critical for check in checks):
        return 1
    return 0


__all__ = ['DoctorCheck', 'collect_checks', 'cmd_doctor']
