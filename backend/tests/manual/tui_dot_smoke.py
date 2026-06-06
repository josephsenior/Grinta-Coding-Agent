from textual.app import App, ComposeResult
from textual.widgets import Static


class TestApp(App):
    def compose(self) -> ComposeResult:
        with open('test_output.txt', 'w', encoding='utf8') as f:
            f.write(repr(Static('\x1fgrinta-diff-ctx\x1f').render()))
        yield Static('\x1fgrinta-diff-ctx\x1ftest')


if __name__ == '__main__':
    app = TestApp()
    app.run(headless=True)
