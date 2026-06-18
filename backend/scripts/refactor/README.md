# Refactor scripts (`backend/scripts/refactor`)

One-off and reusable tooling for mechanical codebase splits (monolith → facade + sibling
submodules). These are maintainer utilities, not part of runtime or CI.

Run from the repository root, for example:

```bash
uv run python backend/scripts/refactor/split_monolith_sibling.py --help
uv run python backend/scripts/refactor/_fix_split_headers.py
```

## Layout

| Script | Purpose |
| --- | --- |
| `split_monolith_sibling.py` | Generic AST line-range splitter |
| `split_*`, `reorganize_*`, `cosmetic_*`, `polish_*` | Historical CLI/backend layout refactors |
| `_run_split_*.py` | Targeted split runners (file edits, LLM, context pipeline, …) |
| `_fix_*.py` | Post-split cleanup (headers, patch targets, cross-imports) |

Verification and CI gates live in [`../verify/`](../verify/README.md).
