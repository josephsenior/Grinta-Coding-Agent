from textual.app import App, ComposeResult
from backend.cli.tui.widgets.activity_card import ActivityCard, _decode_diff_line
from backend.cli.tui.app import _encode_unified_diff_text

class TestApp(App):
    def compose(self) -> ComposeResult:
        diff_text = '''--- backend/cli/main.py
+++ backend/cli/main.py
@@ -1,5 +1,5 @@
 import os
-print('hello')
+print('world')
'''
        encoded = _encode_unified_diff_text(diff_text)
        yield ActivityCard(verb='Edited', detail='main.py', extra_content=encoded)

if __name__ == '__main__':
    app = TestApp()
    app.run(headless=True)
