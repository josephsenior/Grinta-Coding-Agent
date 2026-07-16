"""Validate fresh-machine onboarding evidence for the GA release gate.

Scans ``docs/onboarding_reports/`` for filed reports, counts interactive
``pipx`` and ``source`` runs per platform, and optionally refreshes
``GA_GATE_STATUS.md``.

CI smoke scripts and automated contributor smokes file ``ci-smoke-only``
reports; only ``interactive-fresh-machine`` evidence counts toward the 3×
requirement per path/platform.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_REQUIRED_INTERACTIVE = 3
_REPORT_NAME_RE = re.compile(
    r'^(?P<date>\d{4}-\d{2}-\d{2})_(?P<path>pipx|source)_(?P<os>linux|windows|macos|wsl2)(?:_(?P<n>\d+))?\.md$',
    re.IGNORECASE,
)
_EVIDENCE_RE = re.compile(
    r'\|\s*Evidence type\s*\|\s*(?P<evidence>[^|]+)\|',
    re.IGNORECASE,
)
_PATH_OS_ROWS: tuple[tuple[str, str], ...] = (
    ('pipx', 'linux'),
    ('pipx', 'windows'),
    ('pipx', 'wsl2'),
    ('source', 'linux'),
    ('source', 'windows'),
    ('source', 'wsl2'),
)


@dataclass(frozen=True)
class ReportSummary:
    path: str
    os: str
    evidence: str
    filename: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _reports_dir(root: Path) -> Path:
    return root / 'docs' / 'onboarding_reports'


def _parse_report(path: Path) -> ReportSummary | None:
    match = _REPORT_NAME_RE.match(path.name)
    if match is None:
        return None
    text = path.read_text(encoding='utf-8', errors='replace')
    evidence = 'unknown'
    evidence_match = _EVIDENCE_RE.search(text)
    if evidence_match:
        evidence = evidence_match.group('evidence').strip().lower()
    return ReportSummary(
        path=match.group('path').lower(),
        os=match.group('os').lower(),
        evidence=evidence,
        filename=path.name,
    )


def _collect_reports(reports_dir: Path) -> list[ReportSummary]:
    summaries: list[ReportSummary] = []
    for path in sorted(reports_dir.glob('*.md')):
        if path.name in {'README.md', 'GA_GATE_STATUS.md', 'REPORT_TEMPLATE.md'}:
            continue
        parsed = _parse_report(path)
        if parsed is not None:
            summaries.append(parsed)
    return summaries


def _count_interactive(reports: list[ReportSummary]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {row: 0 for row in _PATH_OS_ROWS}
    for report in reports:
        key = (report.path, report.os)
        if key not in counts:
            continue
        if report.evidence == 'interactive-fresh-machine':
            counts[key] += 1
    return counts


def _count_ci_smoke(reports: list[ReportSummary]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {row: 0 for row in _PATH_OS_ROWS}
    for report in reports:
        key = (report.path, report.os)
        if key not in counts:
            continue
        if report.evidence == 'ci-smoke-only':
            counts[key] += 1
    return counts


def _gate_ready(interactive: dict[tuple[str, str], int]) -> bool:
    required_rows = (
        ('pipx', 'linux'),
        ('pipx', 'windows'),
        ('source', 'linux'),
        ('source', 'windows'),
    )
    return all(
        interactive.get(row, 0) >= _REQUIRED_INTERACTIVE for row in required_rows
    )


def _format_status_table(
    interactive: dict[tuple[str, str], int],
    ci_smoke: dict[tuple[str, str], int],
) -> str:
    lines = [
        '# GA onboarding gate',
        '',
    ]
    if _gate_ready(interactive):
        lines.append('**Ready for GA onboarding sign-off review.**')
    else:
        lines.append('**Not ready for GA sign-off.**')
    lines.extend(
        [
            '',
            'Need **3× interactive pipx** + **3× interactive source** on fresh VMs '
            '(no prior `~/.grinta`). File reports here using '
            '[REPORT_TEMPLATE.md](REPORT_TEMPLATE.md). CI smoke ≠ interactive GA.',
            '',
            '| Path | Interactive filed | CI smoke filed | Notes |',
            '| --- | --- | --- | --- |',
        ]
    )
    notes = {
        ('pipx', 'linux'): 'CI wheel smoke only until interactive reports land',
        (
            'pipx',
            'windows',
        ): 'Partial interactive evidence acceptable while collecting 3×',
        (
            'pipx',
            'wsl2',
        ): 'Run `scripts/smoke/smoke_wsl_layout.sh` inside Ubuntu; manual GA',
        ('source', 'linux'): 'CI only until interactive reports land',
        ('source', 'windows'): 'Contributor smoke + interactive reports',
        (
            'source',
            'wsl2',
        ): 'clone on Linux home, project on `/mnt/c`; `grinta doctor` + interrupt test',
    }
    for path, os_name in _PATH_OS_ROWS:
        label = f'{path} {os_name.upper() if os_name == "wsl2" else os_name.title()}'
        interactive_count = interactive.get((path, os_name), 0)
        ci_count = ci_smoke.get((path, os_name), 0)
        lines.append(
            f'| {label} | {interactive_count} | {ci_count} | {notes[(path, os_name)]} |'
        )
    lines.extend(
        [
            '',
            f'_Last updated by `ga_onboarding_gate.py` on '
            f'{datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}._',
            '',
            'See [RELEASE_CHECKLIST.md](../RELEASE_CHECKLIST.md) before `v1.0.0`.',
            '',
        ]
    )
    return '\n'.join(lines)


def _print_summary(
    interactive: dict[tuple[str, str], int],
    ci_smoke: dict[tuple[str, str], int],
) -> None:
    print('GA onboarding gate summary')
    print(f'Required interactive per path/platform: {_REQUIRED_INTERACTIVE}')
    for path, os_name in _PATH_OS_ROWS:
        i_count = interactive.get((path, os_name), 0)
        c_count = ci_smoke.get((path, os_name), 0)
        status = 'OK' if i_count >= _REQUIRED_INTERACTIVE else 'NEEDS MORE'
        print(
            f'  {path:6} {os_name:7} interactive={i_count} ci-smoke={c_count} [{status}]'
        )
    print('Gate ready:', 'yes' if _gate_ready(interactive) else 'no')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--update-status',
        action='store_true',
        help='Rewrite docs/onboarding_reports/GA_GATE_STATUS.md from scanned reports.',
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    reports_dir = _reports_dir(root)
    reports = _collect_reports(reports_dir)
    interactive = _count_interactive(reports)
    ci_smoke = _count_ci_smoke(reports)
    _print_summary(interactive, ci_smoke)

    if args.update_status:
        status_path = reports_dir / 'GA_GATE_STATUS.md'
        status_path.write_text(
            _format_status_table(interactive, ci_smoke),
            encoding='utf-8',
        )
        print(f'Updated {status_path}')
        return 0

    return 0 if _gate_ready(interactive) else 1


if __name__ == '__main__':
    raise SystemExit(main())
