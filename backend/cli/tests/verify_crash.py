from rich.text import Text

m = '\n[dim #969aad]  (1 tool executed · 2.1s)[/dim]\n'
print('Total length:', len(m))
for i in [38, 39, 40, 41, 42, 43, 44]:
    ctx = m[max(0, i - 2) : i + 4]
    print(f'  i={i}: ctx={ctx!r}')

print()
print('from_markup:')
try:
    t = Text.from_markup(m)
    print('  OK:', str(t))
except Exception as e:
    print('  FAIL:', e)
