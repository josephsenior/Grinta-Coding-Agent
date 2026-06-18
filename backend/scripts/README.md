# Backend scripts (`backend/scripts`)

Small Python utilities used by maintainers and CI. Most day-to-day developer commands (`python scripts/bootstrap_env.py …`, `pytest`, `make`) run from the repository root; larger automation lives in the top-level [`scripts/`](../../scripts/) directory.

## Layout

```text
backend/scripts/
├── verify/       # Import checks, API versioning, reliability gate, optional-deps probe
└── refactor/     # Mechanical split/refactor utilities (maintainer-only)
```

## Verification (`verify/`)

| Script | Purpose |
| --- | --- |
| `check_layer_imports.py` | Layer boundary checks (also wired into pre-commit where configured) |
| `check_fastmcp_import.py` | FastMCP import smoke check |
| `verify_api_versioning.py` | Public API / versioning checks |
| `verify_optional_imports.py` | Optional dependency import probes |
| `reliability_gate.py` | Reliability / migration gate harness |
| `check_file_size.py` | LOC advisory for oversized modules |

Run from the repository root with `python backend/scripts/verify/<script>.py` (or `uv run python …` if you use `uv` as your runner).

Details: [verify/README.md](verify/README.md).

## Refactor (`refactor/`)

Mechanical split helpers used during large-file refactors. See [refactor/README.md](refactor/README.md).
