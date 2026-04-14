import sys, re

f = 'backend/execution/utils/file_editor.py'
text = open(f, encoding='utf-8').read()

new_block = '''def _apply_str_replace(
        self,
        old_content: str,
        old_str: str,
        new_str: str,
        file_path: Path | None = None,
    ) -> str | ToolResult:
        """Apply old_str -> new_str replace with relaxed tolerant whitespace fallback, but validate tree-sitter syntax."""
        exact_count = old_content.count(old_str)

        if exact_count == 1:
            new_content = old_content.replace(old_str, new_str, 1)
        elif exact_count > 1:
            return ToolResult(
                output='',
                error=f'ERROR: old_str matches {exact_count} times. Must be unique.',
                new_content=old_content,
            )
        else:
            tolerant = self._ws_tolerant_replace(old_content, old_str, new_str)
            if isinstance(tolerant, ToolResult):
                fuzzy_result = self._fuzzy_safe_replace(old_content, old_str, new_str)
                if isinstance(fuzzy_result, ToolResult):
                    tolerant.error = self._build_no_match_error(
                        old_content,
                        old_str,
                        mode='normalize_ws/fuzzy_safe',
                    ) + '\\n\\n' + tolerant.error
                    return tolerant
                new_content = fuzzy_result
            else:
                new_content = tolerant'''

text2 = re.sub(r'def _apply_str_replace\(.*?\) -> str \| ToolResult:.*?new_content = fuzzy_result', new_block, text, flags=re.DOTALL)
if text == text2:
    print('NOTHING REPLACED')
    sys.exit(1)

# we also need to remove _resolve_match_mode
text2 = re.sub(r'\s*@staticmethod\s*def _resolve_match_mode\(.*?\)\s*-> str:.*?return \'normalize_ws\' if normalize_ws is not False else \'exact\'', '', text2, flags=re.DOTALL)

open(f, 'w', encoding='utf-8').write(text2)
print("SUCCESS!")
