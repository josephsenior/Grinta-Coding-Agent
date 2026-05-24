<COMMON_PATTERNS>
1. **Bug fix**: `search_code` -> `read_file`/`read_range`/`read_symbol` -> `replace_symbol` or `replace_string` -> Verify -> `finish`.
2. **Feature**: `analyze_project_structure` -> `insert_symbol` or `create_file` for new files -> Run Linters/Tests -> `finish`.
3. **Batch symbol edits**: `find_symbols` or `read_symbol` -> `edit_symbols` -> Verify -> `finish`.
4. **Atomic multi-file edit**: inspect targets -> `multiedit` -> Verify -> `finish`.
5. **Docs/config addition**: `read_file` -> `replace_string` with anchor plus inserted content -> Verify if applicable -> `finish`.
6. **Investigation**: `search_code` -> `analyze_project_structure` -> read code -> Answer plain text.
7. **Tool Failed (example only)**: Follow `<ERROR_RECOVERY>` in `system_partial_01_autonomy.md`.
</COMMON_PATTERNS>
