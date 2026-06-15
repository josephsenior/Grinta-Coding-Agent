import os
import re

mypy_out = '''
backend/tests/unit/cli/tui/test_welcome.py:19: error: Name "_get_screen" is not defined
backend/tests/unit/cli/tui/test_renderer.py:19: error: Name "_get_screen" is not defined
backend/tests/unit/cli/tui/test_renderer.py:198: error: Name "_fill_scrollable_transcript" is not defined
backend/tests/unit/cli/tui/test_mount.py:19: error: Name "_get_screen" is not defined
backend/tests/unit/cli/tui/test_misc.py:20: error: Name "_get_screen" is not defined
backend/tests/unit/cli/tui/test_input_sanitize.py:11: error: Name "_strip_terminal_control_literals" is not defined
backend/tests/unit/cli/tui/test_hud.py:18: error: Name "_get_screen" is not defined
backend/tests/unit/cli/tui/test_communicate.py:21: error: Name "_get_screen" is not defined
backend/tests/unit/cli/tui/test_commands.py:19: error: Name "_get_screen" is not defined
backend/tests/unit/cli/frontend/test_settings.py:12: error: Name "_make_console" is not defined
backend/tests/unit/cli/frontend/test_settings.py:25: error: Name "_console_output" is not defined
backend/tests/unit/cli/frontend/test_repl.py:10: error: Name "_make_console" is not defined
backend/tests/unit/cli/frontend/test_repl.py:12: error: Name "_console_output" is not defined
backend/tests/unit/cli/frontend/test_repl.py:28: error: Name "_supports_prompt_session" is not defined
backend/tests/unit/cli/frontend/test_repl.py:48: error: Name "_prompt_toolkit_available" is not defined
backend/tests/unit/cli/frontend/test_repl.py:58: error: Name "_build_command_completer" is not defined
backend/tests/unit/cli/frontend/test_repl.py:120: error: Name "_parse_slash_command" is not defined
backend/tests/unit/cli/frontend/test_repl.py:139: error: Name "_make_config" is not defined
backend/tests/unit/cli/frontend/test_repl.py:155: error: Name "_configure_redirected_streams" is not defined
backend/tests/unit/cli/frontend/test_repl.py:165: error: Name "_read_piped_stdin" is not defined
backend/tests/unit/cli/frontend/test_repl.py:231: error: Name "_build_help_markdown" is not defined
backend/tests/unit/cli/frontend/test_rendering.py:11: error: Name "_render_thinking_with_diff" is not defined
backend/tests/unit/cli/frontend/test_rendering.py:24: error: Name "_make_console" is not defined
backend/tests/unit/cli/frontend/test_rendering.py:39: error: Name "_console_output" is not defined
backend/tests/unit/cli/frontend/test_misc.py:11: error: Name "_make_config" is not defined
backend/tests/unit/cli/frontend/test_misc.py:49: error: Name "_make_console" is not defined
backend/tests/unit/cli/frontend/test_misc.py:62: error: Name "_console_output" is not defined
'''

file_to_names = {}
for line in mypy_out.strip().splitlines():
    m = re.search(r'^(backend/tests/unit/[^:]+):\d+: error: Name "(_[^"]+)" is not defined', line)
    if m:
        path, name = m.groups()
        file_to_names.setdefault(path, set()).add(name)

for path, names in file_to_names.items():
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if they are already imported explicitly
    if 'from backend.tests.unit.cli.' in content and 'import ' + list(names)[0] in content:
        continue

    # We can just append the explicit imports after the dynamic globals hack
    hack_pattern = r'(globals\(\)\[_name\] = getattr\(_shared, _name\)\s*)'
    names_sorted = sorted(list(names))
    if 'tui' in path:
        shared_path = 'backend.tests.unit.cli.tui._shared'
    else:
        shared_path = 'backend.tests.unit.cli.frontend._shared'
        
    explicit_import = f"from {shared_path} import {', '.join(names_sorted)}\n"
    
    if re.search(hack_pattern, content):
        content = re.sub(hack_pattern, r'\1' + explicit_import, content, count=1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed {path}")
    else:
        print(f"Could not find dynamic hack in {path}")
