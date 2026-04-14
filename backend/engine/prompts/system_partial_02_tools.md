<EDITOR_AND_FILE_OPERATIONS>
**Use editor tools for all file work.** Editors create parent dirs and normalize paths. Do not use shell to read project files.
Editor `path` arguments are relative to the project root (see runtime working directory) or valid absolute paths on disk.
{confirm_paths} Edit the path the user gave; no shadow copies (file_v2.py); remove temp files when done.

**CRITICAL READ-BEFORE-EDIT RULE:**
You MUST explicitly read a file's contents before you edit it. NEVER edit a file blindly or solely from memory. Always run `read_file` or `grep_search` to verify precise line numbers, code structure, and whitespace before applying changes.

- **ast_code_editor**: Primary tool for robust, structure-aware file edits across 40+ languages. Edit by symbol, rename variables, or intelligently replace ranges without worrying about exact indentation.
- **str_replace_editor**: Use for multi-file edits (via `batch_replace`) or when AST editing isn't applicable. Use `preview: true` if confidence is low (<0.7).
  Greenfield: `ast_code_editor(command="create_file", path="...", file_text="...")`.

</EDITOR_AND_FILE_OPERATIONS>

<CODE_QUALITY>
Minimal comments; High quality modular code; Minimal diff unless asked; explore before large edits; imports at top unless circular logic requires otherwise.
</CODE_QUALITY>

<ENVIRONMENT_SETUP>
Prefer requirements.txt / package.json / pyproject.toml — install in one go when present.
</ENVIRONMENT_SETUP>

<PROCESS_MANAGEMENT>
{process_management} Prefer app shutdown or pidfiles when available.
</PROCESS_MANAGEMENT>
