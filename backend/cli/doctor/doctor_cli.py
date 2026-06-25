"""Standalone diagnostics for ``grinta doctor``.

Aggregates environment, configuration, toolchain, and sandbox checks so users
can debug install issues without starting the interactive REPL.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

from backend.cli.doctor.checks import (
    DoctorCheck,
    check_binary as _check_binary,
    check_llm_config as _check_llm_config,
    check_settings_schema as _check_settings_schema,
    collect_doctor_checks,
)
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


def collect_checks(*, verbose: bool = False) -> list[DoctorCheck]:
    """Run all doctor checks and return structured results."""
    return collect_doctor_checks(verbose=verbose)


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
        status_style = (
            CLR_STATUS_OK
            if check.ok
            else (CLR_STATUS_ERR if check.critical else CLR_STATUS_WARN)
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
            f'\n[{CLR_STATUS_WARN}]{len(warnings)} optional check(s) need attention.[/]'
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


__all__ = [
    'DoctorCheck',
    '_check_binary',
    '_check_llm_config',
    '_check_settings_schema',
    'collect_checks',
    'cmd_doctor',
]
