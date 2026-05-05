# Grinta Agent Instructions

## Quick Commands

```bash
# Run all tests (excludes integration/e2e/stress by default)
uv run pytest backend/tests/unit

# Run specific test areas
uv run pytest backend/tests/unit/cli
uv run pytest backend/tests/unit/knowledge
uv run pytest backend/tests/unit/context
uv run pytest backend/tests/integration
uv run pytest backend/tests/e2e

# Run with markers
uv run pytest backend/tests/integration -m integration
uv run pytest backend/tests/e2e -m integration

# Lint
make lint
# or: uv run pre-commit run --all-files

# Typecheck
uv run mypy backend

# Run reliability gate
make reliability-gate
```

## Project Structure

- **backend/cli** - CLI entrypoints and UI components
- **backend/engine** - Core agent engine, tools, orchestrator
- **backend/context** - Context management, vector stores
- **backend/knowledge** - Knowledge base and RAG
- **backend/orchestration** - Agent orchestration, middleware
- **backend/execution** - Action execution server
- **backend/tests** - Unit, integration, e2e, stress tests

## Common Pitfalls

1. **FileEditAction arguments** - The action class accepts `new_str` or `file_text`, NOT `content` or `old_str`. Tests using old arguments will fail.

2. **text_editor command names** - Valid commands are: `read_file`, `create_file`, `insert_text`, `undo_last_edit`, `edit`. NOT `replace_text`.

3. **Test directory** - Use `backend/tests/unit` not just `backend/tests`. The pytest.ini default discovery includes unit+integration+e2e+stress which may be slow.

4. **Pre-existing test failures** - Some tests fail due to:
   - test_tool_display_modules.py::test_text_editor_replace_with_path (invalid command - now fixed)
   - test_local_vector_store_paths.py::test_chromadb_backend_defaults_to_project_storage_memory_chroma (FastEmbed env issue)

5. **browser-use dependencies** - Pinned aiohttp==3.13.3, limits ability to fix some vulnerabilities in optional deps.

6. **Windows line endings** - Some files have CRLF; Git may warn about this on commit.

## Testing Notes

- Tests run via `uv run pytest` (not plain `pytest`)
- Key test paths to verify fixes:
  - `backend/tests/unit/cli/` - CLI tests
  - `backend/tests/unit/knowledge/` - Knowledge base tests
  - `backend/tests/unit/context/` - Context tests  
  - `backend/tests/integration/` - Integration tests
- Some tests need Docker or external services (marked with `@pytest.mark.integration`)

## Dependency Management

- Uses `uv` for package management
- Lock file: `uv.lock`
- Edit constraints in `pyproject.toml`
- Update lock: `uv lock --upgrade`
- Sync environment: `uv sync`