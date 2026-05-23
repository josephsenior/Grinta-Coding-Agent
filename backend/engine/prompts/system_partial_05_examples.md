<COMMON_PATTERNS>
1. **Bug fix**: `search_code` -> `read_file` or `find_symbol` -> `start_file_edit` metadata -> FILE EDITOR MODE content -> Verify -> `finish`.
   - For a one-line import or local fix, prefer a narrow `replace_range` over rewriting the whole file.
2. **Feature**: `analyze_project_structure` -> Add code -> Run Linters/Tests -> `finish`.
3. **Batch symbol edits**: `find_symbol` or `read_symbol` -> `start_file_edit(operation="edit_symbols", symbol_names=[...])` -> FILE EDITOR MODE with repeated `<symbol name="...">` raw blocks -> Verify -> `finish`.
4. **Atomic multi-file edit**: inspect targets -> `start_file_edit(operation="multi_edit", batch_operations=[...])` -> FILE EDITOR MODE with repeated `<edit index="N">` raw blocks -> Verify -> `finish`.
5. **Investigation**: `search_code` -> `analyze_project_structure` -> Read code -> Answer plain text.
6. **Tool Failed (example only)**: Follow `<ERROR_RECOVERY>` in `system_partial_01_autonomy.md`.
</COMMON_PATTERNS>
