from textual.app import App, ComposeResult

from backend.cli.tui.app import _encode_unified_diff_text
from backend.cli.tui.widgets.scan_line import EditCard


class TestApp(App):
    def compose(self) -> ComposeResult:
        diff_text = """--- backend/cli/main.py
+++ backend/cli/main.py
@@ -1,5 +1,5 @@
 import os
-print('hello')
+print('world')
"""
        encoded = _encode_unified_diff_text(diff_text)
        yield EditCard(
            'main.py',
            added=1,
            removed=1,
            encoded_diff=encoded,
        )


if __name__ == '__main__':
    app = TestApp()
    app.run(headless=True)
