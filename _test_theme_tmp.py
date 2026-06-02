"""Run a minimal Textual test to verify finish-style Markdown rendering."""

import sys
sys.path.insert(0, r'C:\Users\GIGABYTE\Desktop\Grinta')

from rich.markdown import Markdown
from backend.cli.theme import get_grinta_pygments_style

# Direct Markdown like the finish tool path uses
finish_msg = """## Done

Here's the code I wrote:

```python
def greet(name):
    print(f"Hello {name}")
```

That's all!"""

md = Markdown(finish_msg, code_theme=get_grinta_pygments_style())
print('CodeBlock theme value:', md.code_theme)
print('Type:', type(md.code_theme))
print()

# Render in a Textual Static via Rich Console
from rich.console import Console
console = Console(force_terminal=True, color_system='truecolor', record=True, width=80)
console.print(md)
out = console.export_text(styles=True)

# Check for Grinta colors
print('Has Grinta keyword color #91abec (145,171,236):', '145;171;236' in out)
print('Has Grinta bg #0a1224 (10,18,36):', '10;18;36' in out)
print('Has monokai bg (39,40,34):', '39;40;34' in out)
print('Has monokai keyword (102,217,239):', '102;217;239' in out)
print()
print('First 800 chars of styled output:')
print(out[:800])
