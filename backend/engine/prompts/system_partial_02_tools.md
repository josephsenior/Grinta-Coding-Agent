<EDITOR_AND_FILE_OPERATIONS>
Editor `path` values create parent dirs where appropriate and normalize safely. {confirm_paths}
Edit the user path directly; no shadow copies; remove temp files when done.

**File API mental model**
- Discovery: `find_symbols` returns candidates.
- Context: `read` for file, range, or symbol bodies. `read(type="symbols")` returns each target as resolved, ambiguous, or not_found.
- New files/symbols: `create`; file creation must not modify existing files.
- Code: `edit_symbols` for modifying/deleting existing symbols; prefer `path` + `qualified_name` + `symbol_kind` for write targets. Use `create` with `type="symbol"` for one complete addition.
- Text/config/docs: `replace_string`; add by anchor -> anchor + content, delete with `new_string=""`.
- Refactor atomically across files: `multiedit`.
- Never write source via shell. Use real newlines/quotes, not serialized JSON strings.

**Examples**
- Find candidates: `find_symbols(query="authenticate")`.
- Read symbols: `read(type="symbols", symbols=[{{"qualified_name": "authenticate_user"}}, {{"qualified_name": "UserService"}}])`.
- README/config add: `replace_string("## Usage\n", "## Usage\n\nExample:\n...")`.
- Delete: `replace_string(old_string="old config block", new_string="")`.
- Add function: `create(type="symbol", target_symbol="login", position="after", content="def logout(...):\n    ...")`.
- Modify method: `edit_symbols(edits=[{{"path": "src/auth.py", "qualified_name": "AuthService.login", "symbol_kind": "method", "new_content": "def login(...):\n    ..."}}])`.
- Multiple functions: `edit_symbols`; implementation + tests: `multiedit`.
</EDITOR_AND_FILE_OPERATIONS>

<CODE_QUALITY>
Minimal diff unless asked. Keep imports at top.
**Structural Integrity:** No circular dependencies; clean abstraction boundaries.
**Defensive Programming:** Graceful failure; thorough error handling.
</CODE_QUALITY>

<PROCESS_MANAGEMENT>
{process_management}
</PROCESS_MANAGEMENT>
