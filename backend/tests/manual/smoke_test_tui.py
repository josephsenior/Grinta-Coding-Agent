"""Smoke test: mount both file_create and file_read cards in the TUI and dump their rendered text."""

from textual.app import App, ComposeResult

from backend.cli.event_rendering.unified_renderer import ActivityRenderer


class TestApp(App):
    def compose(self) -> ComposeResult:
        s = self.console.size
        print(f'\n=== TestApp starting (terminal size {s}) ===\n')

        fc = ActivityRenderer.file_create(
            path='demo.txt', line_count=2
        )
        print('file_create card:')
        print('  verb:', fc.verb)
        print('  detail:', fc.detail)
        print('  secondary:', fc.secondary)
        print('  is_collapsible:', fc.is_collapsible)
        print('  start_collapsed:', fc.start_collapsed)
        print('  extra_lines count:', len(fc.extra_lines))
        print('  syntax_language:', fc.syntax_language)
        print()

        fr = ActivityRenderer.file_read(path='src/main.py', line_range='1:50')
        print('file_read card:')
        print('  verb:', fr.verb)
        print('  detail:', fr.detail)
        print('  is_collapsible:', fr.is_collapsible)
        print('  syntax_language:', fr.syntax_language)
        print()

        fe = ActivityRenderer.file_edit(
            verb='Edited', path='src/main.py', line_range='10:20', added=3, removed=1
        )
        print('file_edit card (for comparison):')
        print('  verb:', fe.verb)
        print('  detail:', fe.detail)
        print('  is_collapsible:', fe.is_collapsible)
        print('  syntax_language:', fe.syntax_language)
        print()

        from backend.cli.tui.widgets.activity_card import ActivityCard as W

        yield W(
            verb=fc.verb,
            detail=fc.detail,
            badge_category=fc.badge_category,
            status='ok',
            outcome=fc.secondary,
            collapsed=fc.start_collapsed,
            collapsible=fc.is_collapsible,
            syntax_language=fc.syntax_language,
        )
        yield W(
            verb=fr.verb,
            detail=fr.detail,
            badge_category=fr.badge_category,
            status='neutral',
            collapsed=fr.start_collapsed,
            collapsible=fr.is_collapsible,
            syntax_language=fr.syntax_language,
        )
        yield W(
            verb=fe.verb,
            detail=fe.detail,
            badge_category=fe.badge_category,
            status='ok',
            outcome=fe.secondary,
            collapsed=fe.start_collapsed,
            collapsible=fe.is_collapsible,
            syntax_language=fe.syntax_language,
        )


if __name__ == '__main__':
    app = TestApp()
    app.run(headless=True, size=(120, 36))
