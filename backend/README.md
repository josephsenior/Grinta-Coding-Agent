# Backend

This folder contains all backend-related code and resources for the Forge project.

## Authentication

Auth invariants (HTTP headers, Socket.IO handshake auth, and the `FORGE_ALLOW_QUERY_TOKEN_AUTH` opt-in) are documented in one place: [docs/AUTH.md](../docs/AUTH.md).

## Structure

```
backend/
├── adapters/       # I/O adapters (e.g., JSON)
├── api/            # FastAPI application and routes
├── cli/            # Command-line interface
├── code_quality/   # Code quality checks
├── controller/     # Agent controller and state management
├── core/           # Core configurations, schemas, and utilities
├── engines/        # AI engines (e.g., Orchestrator)
├── events/         # Event system (Actions, Observations)
├── runtime/        # Execution runtime and tools
├── scripts/        # Backend utility scripts
├── tests/          # Test suite
├── tools/          # Development tools
└── conftest.py     # Pytest configuration
```

## Package Structure

All Python code lives under `backend/`. The CLI and TUI entry points are in `backend/cli/` and `tui/` respectively.  Scripts like `forge` and `forge-tui` are configured in `pyproject.toml`.

## Running Tests

From the project root:
```bash
poetry run pytest backend/tests
```

Or use the Makefile:
```bash
make test-unit
```

## Scripts

Backend scripts are organized in `backend/scripts/` subdirectories:

- **`database/`** - Database setup, backup, and query scripts
- **`setup/`** - Installation and configuration scripts
- **`dev/`** - Development utilities and test helpers
- **`verify/`** - Verification and check scripts
- **`build/`** - Build and code generation scripts
- **`mcp/`** - MCP-related scripts

Run them from the project root:
```bash
python backend/scripts/build/compile_protos.py
python backend/scripts/database/setup_database.py
```

## Development

All Python imports should continue to use `from forge.` - the package structure is abstracted by Poetry's package configuration.
