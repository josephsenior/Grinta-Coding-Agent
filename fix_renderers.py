import pathlib
p = pathlib.Path('backend/engine/prompts/section_renderers.py')
text = p.read_text('utf-8')

# Change 1: Simplify terminal instructions in _render_security
old1 = '''        '- Interactive terminals (	erminal_manager): an empty result with '\n        'has_new_output=false is the normal "still warming up" signal — wait for the next '\n        'tick rather than spamming repeated reads. For servers and log tails, use '\n        'is_background=true on xecute_bash/xecute_powershell.'''
new1 = '''        '- For servers and log tails, use is_background=true on shell executors.\\n'\n        '- Interactive terminals (	erminal_manager): wait for response before sending identical inputs.\''''
text = text.replace(old1, new1)

# Change 2: Autonomy block - finish constraint
old2 = '''            '**Completion (CRITICAL)**: Do NOT call inish if any steps are still in 	odo or doing.''''
new2 = '''            '**Completion (CRITICAL)**: Do NOT call inish if steps are 	odo/doing, unless you need user clarification.''''
text = text.replace(old2, new2)

# Change 3: Terminal manager rule
old3_start = '''        terminal_manager_rule = ('''
old3_end = '''        )'''
new3 = '''        terminal_manager_rule = (\\n            '**Interactive terminal state diagram**: open (spawns process and returns session_id) -> ead -> input -> ead.\\n'\\n            '**Rules**: 1) Reuse session_id, 2) Use mode=delta when reading, 3) Wait for output instead of repeating inputs.'\\n        )'''

import re
text = re.sub(r'        terminal_manager_rule = \(\n            \'\*\*Interactive terminal discipline\*\*:\\n\'[\s\S]+?        \)', new3, text)

# Change 4: Single tool call phrase
old4 = '''            '  - **Constraint**: You MUST emit exactly one tool_call per assistant message. '\n            'Batching multiple function calls in one turn is not supported by this model or configuration.''''
new4 = '''            '  - Only emit one tool call at a time; batching is not supported.''''
text = text.replace(old4, new4)

p.write_text(text, 'utf-8')
