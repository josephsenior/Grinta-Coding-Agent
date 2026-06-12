# Backend scripts (`backend/scripts`)

Small Python utilities used by maintainers and CI. Most day-to-day developer commands (`python scripts/bootstrap_env.py …`, `pytest`, `make`) run from the repository root; larger automation lives in the top-level [`scripts/`](../../scripts/) directory.

## Layout

```text
backend/scripts/
├── verify/       # Import checks, API versioning, reliability gate, optional-deps probe
└── build/        # README only (historical); no build scripts ship here today
```

## Verification (`verify/`)

| Script | Purpose |
| --- | --- |
| `check_layer_imports.py` | Layer boundary checks (also wired into pre-commit where configured) |
| `check_fastmcp_import.py` | FastMCP import smoke check |
| `verify_api_versioning.py` | Public API / versioning checks |
| `verify_optional_imports.py` | Optional dependency import probes |
| `reliability_gate.py` | Reliability / migration gate harness |

Run from the repository root with `python backend/scripts/verify/<script>.py` (or `uv run python …` if you use `uv` as your runner).

Details: [verify/README.md](verify/README.md).
