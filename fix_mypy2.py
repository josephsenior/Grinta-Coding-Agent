import os
import re

mypy_out = '''
backend/tests/unit/cli/tui/test_misc.py:506: error: Name "_fill_scrollable_transcript" is not defined  [name-defined]
backend/tests/unit/cli/tui/test_input_sanitize.py:27: error: Name "_get_screen" is not defined  [name-defined]
backend/tests/unit/cli/frontend/test_event_renderer.py:12: error: Name "_make_console" is not defined  [name-defined]
backend/tests/unit/cli/frontend/test_event_renderer.py:42: error: Name "_console_output" is not defined  [name-defined]
backend/tests/unit/cli/frontend/test_event_renderer.py:64: error: Name "_transcript_needle_count" is not defined  [name-defined]
backend/tests/unit/cli/frontend/test_diff.py:18: error: Name "_make_console" is not defined  [name-defined]
backend/tests/unit/cli/frontend/test_diff.py:20: error: Name "_console_output" is not defined  [name-defined]
backend/tests/unit/cli/frontend/test_diff.py:103: error: Name "_make_config" is not defined  [name-defined]
backend/tests/unit/cli/frontend/test_confirmation.py:13: error: Name "_risk_label" is not defined  [name-defined]
'''

file_to_names = {}
for line in mypy_out.strip().splitlines():
    m = re.search(r'^(backend/tests/unit/[^:]+):\d+: error: Name "(_[^"]+)" is not defined', line)
    if m:
        path, name = m.groups()
        file_to_names.setdefault(path, set()).add(name)

for path, names in file_to_names.items():
    if not os.path.exists(path):
        continue
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check if they are already imported explicitly
    import_list = []
    for name in names:
        if 'import ' + name not in content and 'from ' not in name:
            import_list.append(name)
            
    if not import_list:
        continue

    # We can just append the explicit imports after the dynamic globals hack
    hack_pattern = r'(globals\(\)\[_name\] = getattr\(_shared, _name\)\s*)'
    names_sorted = sorted(list(import_list))
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
