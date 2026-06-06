<COMMON_PATTERNS>
1. **Bug fix**: `grep`/`find_symbols` -> `read` -> `edit_symbols` or `replace_string` -> Verify -> final summary.
2. **Feature**: `analyze_project_structure` -> `create` / `replace_string` / `edit_symbols` / `multiedit` -> Run Linters/Tests -> final summary.
3. **Batch symbol edits**: `find_symbols` or `read` -> `edit_symbols` -> Verify -> final summary.
4. **Atomic multi-file edit**: inspect targets -> `multiedit` -> Verify -> final summary.
5. **Docs/config addition**: `read` -> `replace_string` with anchor plus inserted content -> Verify if applicable -> final summary.
6. **Investigation**: `grep` / `glob` -> `analyze_project_structure` -> read code -> Answer plain text.
7. **Tool Failed (example only)**: Follow `<ERROR_RECOVERY>`.
</COMMON_PATTERNS>
