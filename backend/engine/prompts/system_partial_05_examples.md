<COMMON_PATTERNS>
Runtime tools: {available_tools_summary}

1. **Bug fix**: {search_tools} -> {read_tool} -> {edit_tools} -> Verify -> final summary.
2. **Feature**: {planning_hint} -> {analyze_tool} -> {edit_tools} -> {terminal_tool} (tests/lint) -> final summary.
3. **Batch symbol edits**: {search_tools} -> {read_tool} -> {edit_symbols_tool} -> Verify -> final summary.
4. **Atomic multi-file edit**: inspect targets -> {multiedit_tool} -> Verify -> final summary.
5. **Docs/config addition**: {read_tool} -> {replace_string_tool} with anchor plus inserted content -> Verify if applicable -> final summary.
6. **Investigation**: {search_tools} -> {analyze_tool} -> {read_tool} -> Answer plain text.
7. **Destructive/risky change**: {destructive_confirmation_step} -> {checkpoint_step} -> Verify -> final summary.
8. **Tool failed**: Follow `<ERROR_RECOVERY>`. Fallbacks: {adjacent_tool_fallback}. {failure_escalation_step}.
</COMMON_PATTERNS>
