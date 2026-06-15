# Backend

This folder contains all backend-related code and resources for the Grinta project.

## Structure

```text
backend/
├── cli/             # Terminal UI, REPL, and CLI entry
├── context/         # Context memory and compaction
├── core/            # Shared config, schemas, logging, and bootstrap
├── engine/          # LLM-facing agent engine and tools
├── evaluation/      # Agent eval pack and related helpers
├── execution/       # Local runtime execution and policy enforcement
├── inference/       # Model/provider abstraction layer
├── integrations/    # External adapters (e.g. MCP plumbing)
├── knowledge/       # Knowledge base logic
├── ledger/          # Record stream, event types, serialization
├── orchestration/   # Session orchestration loop and services
├── persistence/     # Local file-backed persistence
├── playbooks/       # Built-in playbook content and engine
├── scripts/         # Backend utility scripts
├── security/        # Security analysis and policy checks
├── telemetry/       # Lightweight instrumentation
├── tools/           # Repo maintenance utilities (e.g. trajectory sanitization)
├── utils/           # Shared utilities (LSP client, imports, etc.)
├── validation/    # Validation and completion guards
├── tests/         # Test suite
└── conftest.py    # Pytest configuration
```

## Package Structure

Most application code lives under `backend/`. The supported interactive surface is the terminal CLI in `backend/cli/`, launched through `launch.entry` or `python -m backend.cli.entry`.

## Running Tests

From the project root, `uv run pytest` (no path) discovers all of `backend/tests` per the repo [`pytest.ini`](../pytest.ini). To match the required PR gates (unit only):

```bash
uv run pytest backend/tests/unit
```

To run the full tree explicitly:

```bash
uv run pytest backend/tests
```

Or use the Makefile:

```bash
make test-unit
```

## Scripts

`backend/scripts/` currently holds **verification** utilities used in CI and local gates (`verify/`). One-off automation, smoke installs, and eval helpers live under the repository root [`scripts/`](../scripts/) instead.

From the project root:

```bash
python backend/scripts/verify/check_layer_imports.py
python backend/scripts/verify/reliability_gate.py --phase full
```

See [`backend/scripts/README.md`](scripts/README.md) for the full list.

## Development

Backend code imports from `backend.*`. The supported entrypoints are the CLI under `backend/cli/` and the portable launcher in `launch/`.

### CLI Mixin Typing Convention

When extracting logic into CLI mixins (for example in `backend/cli/repl/` or
`backend/cli/event_rendering/`), define host interfaces in
`backend/cli/_typing.py` and import them into mixins instead of re-declaring
`TYPE_CHECKING`-only host stubs per file.

- Keep shared host contracts in `backend/cli/_typing.py` as `Protocol` classes.
- In mixins, cast `self` to the relevant host protocol where needed.
- Prefer this shared protocol approach over file-local structural stubs so
  typing and lint behavior stays consistent across extracted modules.
