# Grinta utilities (`backend/utils`)

Small shared helpers used across orchestration, execution, CLI, and inference.

## Dynamic imports (`import_utils.py`)

`import_from(qual_name)` loads any object from a fully qualified module path (for example `'builtins.ValueError'`).

`get_impl(base_cls, impl_name)` returns `base_cls` when `impl_name` is `None`, otherwise imports the named class and checks that it is a compatible subclass of `base_cls`. Results are cached.

Real call sites include:

- `backend/execution/runtime_factory.py` — resolve the concrete `Runtime` implementation.
- `backend/core/config/config_loader.py` — optional `Agent` classpath from settings.
- `backend/core/config/mcp_config.py` — optional MCP config class override.
- `backend/persistence/conversation/conversation_validator.py` — store/validator class selection.

Use fully qualified names under the `backend.` package (or stdlib/third-party modules) in configuration — not legacy `app.*` placeholders.
