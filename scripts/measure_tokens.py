"""Historical helper for estimating aggregate tool-schema token count.

Constructing an accurate OpenAI-style tool list requires a fully wired
``OrchestratorPlanner`` (``AppConfig`` / ``LLM`` / ``OrchestratorSafetyManager``),
which this standalone script does not build.

For dead-code and maintenance scans, prefer::

    uv run vulture

For prompt/tool size debugging at runtime, use ``APP_DEBUG_PROMPT_METRICS`` (see
``OrchestratorPlanner`` / CLI) or inspect ``build_toolset()`` from a REPL session.

See ``docs/investigations/dead_code_audit_report.md``.
"""

from __future__ import annotations

import sys


def main() -> None:
    sys.stderr.write(
        'measure_tokens.py no longer mirrors the planner stack; '
        'see docs/investigations/dead_code_audit_report.md\n'
    )
    raise SystemExit(2)


if __name__ == '__main__':
    main()
