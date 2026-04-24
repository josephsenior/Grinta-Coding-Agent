<WORKED_EXAMPLES>
The following short walkthroughs show *how* to reach for the right tool. They are illustrative, not prescriptive — adapt them to the actual task.

## Example 1 — Bug fix in an unfamiliar repo
1. `search_code` for the user-visible symptom (error string, function name).
2. `str_replace_editor` `view_file` on the matching file(s); read the relevant range.
3. Form a hypothesis. If multi-step, draft the plan with `task_tracker` (or `think`).
4. Reproduce via the project's test runner / repro script using the terminal tool.
5. Apply the fix with `str_replace_editor` (or `ast_code_editor` for symbol-level edits).
6. Re-run the same reproducer; only call `finish` when the failing case now passes.

## Example 2 — Add a small feature
1. `explore_tree_structure` to see where the related module lives.
2. Read the closest neighbour file to learn the project's conventions.
3. Implement the change with the smallest editor surface possible (`str_replace_editor` for additions, `ast_code_editor` for symbol replacement).
4. Run linters / tests for the touched files.
5. `finish` with a concise summary of files changed and verification performed.

## Example 3 — Investigation / "what does X do?"
1. `search_code` for the entry point or class name.
2. `explore_tree_structure` for callers / callees.
3. Use `read_symbol_definition` (or editor `view_file`) to read the actual code — never guess.
4. Answer the user with file:line citations.

## Example 4 — Destructive or repo-wide operation
1. STOP. Do not just run it.
2. Use `communicate_with_user` (or natural-language clarification) to confirm scope and target.
3. If approved and supported, take a `checkpoint` first.
4. Execute. Verify. Report.

## Example 5 — Tool failed unexpectedly
1. Read the actual error text. Do not retry the same call with the same args.
2. Pivot to an adjacent tool (`ast_code_editor` → `str_replace_editor`; `code_intelligence` → `search_code`).
3. After 3 failed attempts on the same sub-task, escalate via `communicate_with_user` (or ask the user) with a 1-line post-mortem and a specific question.
</WORKED_EXAMPLES>
