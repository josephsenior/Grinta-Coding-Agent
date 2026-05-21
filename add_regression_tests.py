"""Add regression tests to test_fn_call_converter.py"""

# Read current file
with open(r'C:\Users\GIGABYTE\Desktop\Grinta\backend\tests\unit\inference\test_fn_call_converter.py', 'r') as f:
    content = f.read()

# New test class to add
new_tests = '''

# ── Regression tests for XML parser issues ─────────────────────────────────


class TestXmlParserRegression:
    """Regression tests for XML parser issues.

    Tests the specific bugs reported:
    1. Trailing text false positives when file_edit blocks are stripped
    2. Content containing pseudo-tags, quotes, braces
    3. Consecutive valid calls with multiline content
    4. Trailing prose outside XML block
    """

    def _make_file_editor_tool(self):
        return {
            'type': 'function',
            'function': {
                'name': 'file_editor',
                'description': 'File editor tool',
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'command': {'type': 'string'},
                        'path': {'type': 'string'},
                        'content': {'type': 'string'},
                        'security_risk': {'type': 'string'},
                    },
                    'required': ['command', 'path', 'security_risk'],
                },
            },
        }

    def test_trailing_text_false_positive_with_file_edit_blocks(self):
        """Regression: trailing text error when file_edit blocks are stripped.

        Previously the parser used positions from the modified param_body
        but checked trailing against fn_body, causing false positives
        when multi_edit had nested file_edit blocks.
        """
        tools = [self._make_file_editor_tool()]
        # This content has file_edit blocks that get stripped - the trailing check
        # should NOT fail because we now use the stripped body for position tracking
        content = (
            '<function=file_editor>\\n'
            '<parameter=command>multi_edit