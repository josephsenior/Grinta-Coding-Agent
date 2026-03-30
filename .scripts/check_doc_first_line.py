import ast
from pathlib import Path

p = Path(
    'C:/Users/youse/Bureau/Joseph/App/evaluation/benchmarks/versicode/metric/compute_migration_cdc_score.py'
)
s = p.read_text(encoding='utf-8')
mod = ast.parse(s)
for node in mod.body:
    if isinstance(node, ast.FunctionDef):
        if doc := ast.get_docstring(node):
            first_line = doc.strip().splitlines()[0]
            last_char = first_line[-1] if first_line else ''
            print(
                f'{node.name}: {first_line!r} -> last char: {last_char!r} (ord: {(ord(last_char) if last_char else "")})'
            )
