import re

def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace literal '\\n' with actual '\n'
    fixed = content.replace("'\\\\n'.join", "'\\n'.join")
    
    # Also fix <search_results> strings in search_code.py, they have \\n
    fixed = fixed.replace("<search_results>\\n", "<search_results>\n")
    fixed = fixed.replace("\\n</search_results>", "\n</search_results>")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(fixed)

fix_file('backend/engine/tools/analyze_project_structure.py')
fix_file('backend/engine/tools/search_code.py')
print("Fixed both files.")
