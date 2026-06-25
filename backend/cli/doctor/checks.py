"""Shared diagnostic checks for ``grinta doctor`` and in-session ``/health``."""

from __future__ import annotations

import importlib
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DoctorCheck:
    """One row in a doctor or health report."""

    name: str
    ok: bool
    detail: str
    critical: bool = True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def check_version() -> DoctorCheck:
    try:
        from backend import get_version

        version = get_version()
    except Exception as exc:
        return DoctorCheck('version', False, f'unavailable: {exc}')
    return DoctorCheck('version', True, version, critical=False)


def check_python() -> DoctorCheck:
    return DoctorCheck(
        'python',
        True,
        f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}',
        critical=False,
    )


def check_platform() -> DoctorCheck:
    from backend.core.os_capabilities import OS_CAPS

    name = platform.system()
    detail = f'{name} ({sys.platform})'
    sep = ' · '
    if OS_CAPS.is_linux:
        detail += f'{sep}linux'
    elif OS_CAPS.is_windows:
        detail += f'{sep}windows'
    elif OS_CAPS.is_macos:
        detail += f'{sep}macos'
    return DoctorCheck('platform', True, detail, critical=False)


def check_settings_file() -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path

    path = Path(get_canonical_settings_path())
    if not path.is_file():
        return DoctorCheck(
            'settings',
            False,
            f'missing: {path} (run `grinta init` or copy settings.template.json)',
        )
    return DoctorCheck('settings', True, str(path))


def check_settings_schema() -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path
    from backend.core.config import AppConfig
    from backend.core.config.config_loader import load_from_json
    from backend.core.constants import DEFAULT_AGENT_NAME

    path = get_canonical_settings_path()
    if not Path(path).is_file():
        return DoctorCheck(
            'settings_schema', False, 'settings.json not found', critical=False
        )

    try:
        cfg = AppConfig()
        load_from_json(cfg, path)
    except Exception as exc:
        return DoctorCheck('settings_schema', False, f'load failed: {exc}')

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
        f'agent={DEFAULT_AGENT_NAME} mode={orchestrator.mode} autonomy={orchestrator.autonomy_level} profile={profile}',
        critical=False,
    )


def check_llm_config(*, model_hint: str | None = None) -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path
    from backend.core.config import AppConfig
    from backend.core.config.api_key_manager import api_key_manager
    from backend.core.config.config_loader import load_from_json

    if model_hint and str(model_hint).strip() and str(model_hint).strip() != '(not set)':
        model = str(model_hint).strip()
        return DoctorCheck('model', True, model, critical=False)

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
        from backend.inference.local_model import is_local_llm_config

        if is_local_llm_config(llm_cfg):
            provider = api_key_manager.extract_provider(model)
            return DoctorCheck(
                'llm',
                True,
                f'provider={provider} model={model} key=not required (local)',
            )
        return DoctorCheck(
            'llm',
            False,
            f'model={model} but no API key resolved (set LLM_API_KEY or provider env var)',
        )

    provider = api_key_manager.extract_provider(model)
    return DoctorCheck('llm', True, f'provider={provider} model={model} key=resolved')


def check_execution_profile() -> DoctorCheck:
    from backend.core.app_paths import get_canonical_settings_path
    from backend.core.config import AppConfig
    from backend.core.config.config_loader import load_from_json
    from backend.execution.sandboxing import resolve_execution_sandbox_policy

    path = get_canonical_settings_path()
    if not Path(path).is_file():
        return DoctorCheck(
            'execution', False, 'settings.json not found', critical=False
        )

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


def check_binary(name: str, *, critical: bool = True) -> DoctorCheck:
    path = shutil.which(name)
    if path:
        return DoctorCheck(name, True, path, critical=critical)
    return DoctorCheck(name, False, 'not found on PATH', critical=critical)


def check_debugpy() -> DoctorCheck:
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


def check_optional_imports() -> DoctorCheck:
    script = (
        _repo_root() / 'backend' / 'scripts' / 'verify' / 'verify_optional_imports.py'
    )
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
        return DoctorCheck(
            'optional_imports',
            True,
            'no top-level optional import leaks',
            critical=False,
        )
    detail = (proc.stderr or proc.stdout or 'failed').strip().splitlines()
    first = detail[0] if detail else 'failed'
    return DoctorCheck('optional_imports', False, first, critical=False)


def check_editing_stack() -> DoctorCheck:
    from backend.engine.tools.health_check import run_production_health_check

    try:
        result = run_production_health_check(raise_on_failure=False)
    except Exception as exc:
        return DoctorCheck('editing_stack', False, str(exc), critical=False)

    overall = result.get('overall_status', 'UNKNOWN')
    if overall == 'HEALTHY':
        return DoctorCheck(
            'editing_stack', True, 'structure editor + atomic refactor', critical=False
        )
    se = result.get('structure_editor', {})
    msg = se.get('message', overall) if isinstance(se, dict) else overall
    return DoctorCheck('editing_stack', False, str(msg), critical=False)


def collect_doctor_checks(*, verbose: bool = False) -> list[DoctorCheck]:
    """Run the full ``grinta doctor`` check suite."""
    checks: list[DoctorCheck] = [
        check_version(),
        check_python(),
        check_platform(),
        check_settings_file(),
        check_settings_schema(),
        check_llm_config(),
        check_execution_profile(),
        check_binary('git'),
        check_binary('rg'),
        check_debugpy(),
        check_optional_imports(),
    ]
    if verbose:
        checks.append(check_editing_stack())
    return checks


def collect_health_checks(*, model_hint: str | None = None) -> list[DoctorCheck]:
    """Fast in-session subset shared with ``/health``."""
    return [
        check_debugpy(),
        check_binary('git'),
        check_binary('rg'),
        check_llm_config(model_hint=model_hint),
    ]


def format_health_report_lines(checks: list[DoctorCheck]) -> list[str]:
    """Render health checks as plain text lines for REPL/TUI."""
    lines = ['Self-check:']
    for check in checks:
        mark = 'ok ' if check.ok else 'FAIL'
        lines.append(f'  [{mark}] {check.name}: {check.detail}')
    return lines


__all__ = [
    'DoctorCheck',
    'check_binary',
    'check_debugpy',
    'check_editing_stack',
    'check_execution_profile',
    'check_llm_config',
    'check_optional_imports',
    'check_platform',
    'check_python',
    'check_settings_file',
    'check_settings_schema',
    'check_version',
    'collect_doctor_checks',
    'collect_health_checks',
    'format_health_report_lines',
]
