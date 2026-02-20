# Backend

This folder contains all backend-related code and resources for the Forge project.

## Authentication

Auth invariants (HTTP headers, Socket.IO handshake auth, and the `FORGE_ALLOW_QUERY_TOKEN_AUTH` opt-in) are documented in one place: [docs/AUTH.md](../docs/AUTH.md).

## Structure

```
backend/
├── forge/          # Main Python package (imported as `forge`)
├── tests/          # Test suite
├── scripts/        # Backend utility scripts
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
