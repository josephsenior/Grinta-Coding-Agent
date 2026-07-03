<COMMON_PATTERNS>
1. **Bug fix**: {bug_fix_pattern}
2. **Feature**: {feature_pattern}
3. **Targeted text edit**: {search_tools} -> {read_tool} -> {replace_string_tool} -> Verify -> final summary.
4. **Atomic batch edit**: inspect targets -> {multiedit_tool} -> Verify -> final summary.
5. **Docs/config addition**: {read_tool} -> {replace_string_tool} with anchor plus inserted content -> Verify if applicable -> final summary.
6. **Investigation**: {search_tools} -> {analyze_tool} -> {read_tool} -> Answer plain text.
7. **Destructive/risky change**: {destructive_confirmation_step} -> {checkpoint_step} -> Verify -> final summary.
8. **Tool failed**: Follow `<ERROR_RECOVERY>`. Fallbacks: {adjacent_tool_fallback}. {failure_escalation_step}.
</COMMON_PATTERNS>
