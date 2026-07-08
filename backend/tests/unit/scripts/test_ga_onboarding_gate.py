"""Integration tests for ga_onboarding_gate report scanning."""

from __future__ import annotations

from pathlib import Path

from backend.scripts.verify.ga_onboarding_gate import (
    _collect_reports,
    _count_ci_smoke,
    _count_interactive,
    _gate_ready,
    _parse_report,
)


def test_parse_report_reads_evidence_type(tmp_path: Path) -> None:
    report = tmp_path / '2026-07-08_source_windows_1.md'
    report.write_text(
        '# report\n\n| Evidence type | interactive-fresh-machine |\n',
        encoding='utf-8',
    )
    parsed = _parse_report(report)
    assert parsed is not None
    assert parsed.path == 'source'
    assert parsed.os == 'windows'
    assert parsed.evidence == 'interactive-fresh-machine'


def test_gate_not_ready_without_interactive_reports(tmp_path: Path) -> None:
    report = tmp_path / '2026-07-08_source_windows_2.md'
    report.write_text(
        '# report\n\n| Evidence type | ci-smoke-only |\n',
        encoding='utf-8',
    )
    reports = _collect_reports(tmp_path)
    interactive = _count_interactive(reports)
    ci_smoke = _count_ci_smoke(reports)
    assert interactive[('source', 'windows')] == 0
    assert ci_smoke[('source', 'windows')] == 1
    assert not _gate_ready(interactive)
