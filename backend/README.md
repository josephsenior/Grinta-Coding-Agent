# Backend

This folder contains all backend-related code and resources for the Grinta project.

## Structure

```
backend/
├── core/            # Shared config, schemas, logging, and bootstrap
├── orchestration/   # Session orchestration loop and services
├── engine/          # LLM-facing agent engine
├── ledger/          # Record stream, persistence, and serialization
├── context/         # Context memory and compaction
├── execution/       # Local runtime execution and policy enforcement
├── inference/       # Model/provider abstraction layer
├── knowledge/       # Knowledge base logic
├── persistence/     # Local file-backed persistence
├── playbooks/       # Built-in playbook content and engine
├── security/        # Security analysis and policy checks
├── validation/      # Validation and code-quality checks
├── scripts/         # Backend utility scripts
├── tests/           # Test suite
└── conftest.py      # Pytest configuration
```

## Package Structure

Most application code lives under `backend/`. The CLI entry point is `backend/cli/`. The Python API client used by tests and scripts is in `client/`. The `app` console script is configured in `pyproject.toml`.

## Running Tests

From the project root:
```bash
uv run pytest backend/tests
```

Or use the Makefile:
```bash
make test-unit
```

## Scripts

Backend scripts are organized in `backend/scripts/` subdirectories:

- **`setup/`** - Installation and configuration scripts
- **`dev/`** - Development utilities and test helpers
- **`verify/`** - Verification and check scripts
- **`build/`** - Build and code generation scripts
- **`mcp/`** - MCP-related scripts

Run them from the project root:
```bash
python backend/scripts/build/compile_protos.py
```

## Development

Backend code imports from `backend.*`. The automation client imports from `client.*` or the package root `client`.
