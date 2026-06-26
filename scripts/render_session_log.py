#!/usr/bin/env python3
"""Regenerate session.txt from session.jsonl on demand."""

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
        '--output',
        type=Path,
        default=None,
        help='Output path for session.txt (default: alongside jsonl)',
    )
    args = parser.parse_args()

    log_path = args.log_path.resolve()
    if log_path.is_dir():
        log_path = log_path / 'session.jsonl'
    out_path = (args.output or log_path.parent / 'session.txt').resolve()

    from backend.core.logging.session_log_audit import load_session_events
    from backend.core.logging.session_log_renderer import write_session_transcript

    events = load_session_events(log_path)
    write_session_transcript(events, out_path)
    print(f'Wrote {out_path} ({len(events)} events)')


if __name__ == '__main__':
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    main()
