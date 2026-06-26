#!/usr/bin/env python3
"""Generate session.audit.txt and session.txt from session.jsonl."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'log_path',
        type=Path,
        help='Path to session.jsonl (or session directory)',
    )
    parser.add_argument(
        '-o',
        '--output-dir',
        type=Path,
        default=None,
        help='Directory for derived artifacts (default: same as log)',
    )
    args = parser.parse_args()

    log_path = args.log_path.resolve()
    if log_path.is_dir():
        log_path = log_path / 'session.jsonl'
    out_dir = (args.output_dir or log_path.parent).resolve()
    transcript_path = out_dir / 'session.txt'
    report_path = out_dir / 'session.audit.txt'
    from backend.core.logging.session_log_audit import analyze_session

    result = analyze_session(log_path, transcript_path, report_path)
    print(f'Wrote transcript: {transcript_path}')
    print(f'Wrote audit report: {report_path}')
    print(f'Events: {result.kept_lines:,}  Verdict: {result.verdict}')


if __name__ == '__main__':
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    main()
