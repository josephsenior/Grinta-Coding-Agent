from pathlib import Path

p = Path(
    'C:/Users/youse/Bureau/Joseph/Forge/evaluation/benchmarks/versicode/metric/compute_migration_cdc_score.py'
)
s = p.read_text(encoding='utf-8')
lines = s.splitlines()
for name in ['is_correct_parameter_count', 'check_keyword_parameters', 'with_correct']:
    print('==', name)
    idx = next((i for i, line in enumerate(lines) if f'def {name}' in line))
    for j in range(idx - 3, idx + 7):
        if 0 <= j < len(lines):
            print(f'{j + 1}: {lines[j]!r}')
    print('---')
