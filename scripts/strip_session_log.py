#!/usr/bin/env python3
"""Strip noisy session log lines and produce a readable audit summary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log_path', type=Path)
    parser.add_argument(
        '-o',
        '--output-dir',
        type=Path,
        default=None,
        help='Directory for stripped log and report (default: same as log)',
    )
    args = parser.parse_args()

    log_path = args.log_path.resolve()
    out_dir = (args.output_dir or log_path.parent).resolve()
    stem = log_path.stem
    stripped_path = out_dir / f'{stem}.stripped.log'
    report_path = out_dir / f'{stem}.audit.txt'
    from backend.core.logging.session_log_audit import analyze_session

    result = analyze_session(log_path, stripped_path, report_path)
    print(f'Wrote stripped log: {stripped_path} ({result.kept_lines:,} lines)')
    print(f'Wrote audit report: {report_path}')
    print(f'Verdict: {result.verdict}')


if __name__ == '__main__':
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    main()
