"""CLI for scoring the cross-agent comparison pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from backend.evaluation.agent_eval_pack import (
    build_results_template,
    compare_agents,
    load_eval_pack,
    load_results_document,
    render_markdown_summary,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Score vendor-neutral coding-agent evaluation results.',
    )
    parser.add_argument(
        '--pack',
        default='scripts/evals/agent_comparison_pack.json',
        help='Path to the eval pack JSON file.',
    )
    parser.add_argument(
        '--format',
        choices=('markdown', 'json'),
        default='markdown',
        help='Output format for scored comparisons.',
    )
    parser.add_argument(
        '--write-template',
        nargs=2,
        metavar=('AGENT_ID', 'OUTPUT_PATH'),
        help='Write a blank results template for one agent and exit.',
    )
    parser.add_argument(
        'result_files',
        nargs='*',
        help='One or more scored results JSON files to compare.',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    pack = load_eval_pack(args.pack)

    if args.write_template is not None:
        agent_id, output_path = args.write_template
        template = build_results_template(pack, agent_id)
        Path(output_path).write_text(
            json.dumps(template, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )
        return 0

    if not args.result_files:
        parser.error('Provide at least one results JSON file, or use --write-template.')

    results_documents = [load_results_document(path) for path in args.result_files]
    comparison = compare_agents(pack, results_documents)

    if args.format == 'json':
        print(json.dumps(comparison, indent=2, ensure_ascii=False))
    else:
        print(render_markdown_summary(comparison))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())