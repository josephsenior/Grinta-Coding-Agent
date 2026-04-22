"""Tests for :mod:`backend.core.content_escape_repair`.

The heuristic is deliberately conservative — false positives corrupt files —
so these tests lock down the thresholds rather than aiming for exhaustive
coverage.
"""

from __future__ import annotations

from backend.core.content_escape_repair import (
    CONTENT_ARG_NAMES,
    has_literal_escape_residue,
    repair_arguments_in_place,
    repair_literal_escapes,
)


class TestHasLiteralEscapeResidue:
    def test_no_residue_plain_html(self) -> None:
        content = '<div>\n  <p>Hello</p>\n</div>\n'
        assert not has_literal_escape_residue(content, 'index.html')

    def test_detects_over_escaped_html_single_line(self) -> None:
        content = '<div class=\\"foo\\">\\n  <p>Hi</p>\\n</div>'
        assert has_literal_escape_residue(content, 'index.html')

    def test_detects_over_escaped_css_single_line(self) -> None:
        content = '.btn {\\n  color: red;\\n  font-size: 14px;\\n}'
        assert has_literal_escape_residue(content, 'styles.css')

    def test_rejects_unstructured_path(self) -> None:
        content = 'hello\\nworld\\nthere\\nmore'
        assert not has_literal_escape_residue(content, 'notes.txt')
        # .md is now in the heuristic set (see class-level docstring),
        # so heavy residue on a short blob with no real newlines triggers.
        # The rejection target here is genuinely unstructured paths (.txt).

    def test_markdown_is_heuristic_repaired(self) -> None:
        # Markdown now participates with the same ratio gate as code.
        heavy = 'one\\ntwo\\nthree\\nfour'  # no real newlines, lots of \n
        assert has_literal_escape_residue(heavy, 'README.md')
        # But a docstring-style usage inside prose is untouched:
        light = 'Here is the code:\n```\nfoo\\n\n```\n'
        assert not has_literal_escape_residue(light, 'README.md')

    def test_strict_markup_detects_double_backslash_residue(self) -> None:
        # The exact shape seen in the Kimi K2.5 log: literal ``\\n`` survived
        # into a CSS file and broke tree-sitter. Must be caught here.
        content = '.btn {\n  display: flex;\\\\n    gap: 4px;\n}\n'
        assert has_literal_escape_residue(content, 'styles.css')

    def test_strict_markup_catches_pure_double_backslash_blob(self) -> None:
        # All separators are ``\\n`` (no real newlines, no single-backslash
        # residue). The single-pass regex alone wouldn't catch this.
        content = '<div>\\\\n  <p>hi</p>\\\\n</div>'
        assert has_literal_escape_residue(content, 'index.html')

    def test_respects_even_parity_double_backslash(self) -> None:
        # ``\\n`` in Python source == two chars: backslash+n.  That already has
        # even parity (the preceding backslash escapes this backslash), so the
        # pattern should NOT match.  This protects legitimate code that writes
        # escape syntax.
        content = 'print("line1\\\\nline2")\n'
        assert not has_literal_escape_residue(content, 'demo.py')

    def test_ratio_gate_tolerates_mixed_content(self) -> None:
        # Python docstring showing escape syntax, surrounded by real newlines.
        # Ratio of literal ``\n`` pairs to real newlines is ~1:3, under the 2x
        # gate, so we leave it alone.
        content = 'def f():\n    """Use \\n for newlines."""\n    return 1\n'
        assert not has_literal_escape_residue(content, 'f.py')

    def test_empty_and_non_string(self) -> None:
        assert not has_literal_escape_residue('', 'x.html')
        assert not has_literal_escape_residue(None, 'x.html')  # type: ignore[arg-type]
        assert not has_literal_escape_residue(123, 'x.html')  # type: ignore[arg-type]


class TestRepairLiteralEscapes:
    def test_repairs_html_over_escape(self) -> None:
        content = '<div class=\\"foo\\">\\n  <p>Hi</p>\\n</div>'
        report = repair_literal_escapes(content, 'index.html')
        assert report.changed
        assert report.replacements == 4  # \" \" \n \n
        assert report.content == '<div class="foo">\n  <p>Hi</p>\n</div>'
        assert report.reason == 'repaired'

    def test_noop_on_clean_content(self) -> None:
        content = '<div>\n  <p>Hello</p>\n</div>\n'
        report = repair_literal_escapes(content, 'index.html')
        assert not report.changed
        assert report.content == content

    def test_noop_on_unstructured(self) -> None:
        content = 'literal \\n marker\nand a real newline'
        report = repair_literal_escapes(content, 'notes.txt')
        assert not report.changed
        assert report.reason == 'not_applicable'

    def test_repairs_strict_markup_double_backslash(self) -> None:
        # Kimi-style over-escape: ``\\n`` pairs inside CSS source.
        content = '.btn {\n  display: flex;\\\\n    gap: 4px;\n}\n'
        report = repair_literal_escapes(content, 'styles.css')
        assert report.changed
        assert '\\\\n' not in report.content
        assert 'display: flex;\n    gap: 4px;' in report.content
        assert report.reason == 'repaired'

    def test_repairs_mixed_single_and_double_backslash_html(self) -> None:
        # Single-backslash residue pass runs first, then the strict
        # double-backslash pass for markup files.
        content = '<div class=\\"a\\">\\\\n  <p>hi</p>\\\\n</div>'
        report = repair_literal_escapes(content, 'index.html')
        assert report.changed
        assert report.content == '<div class="a">\n  <p>hi</p>\n</div>'

    def test_repairs_tabs_and_cr(self) -> None:
        content = 'x\\ty\\rz\\na'
        # Not enough ratio signal on a one-line sample — give it more structure
        report = repair_literal_escapes(content, 'x.py')
        # Heuristic: real_newlines=0, residue_count>=2 → repair fires
        assert report.changed
        assert report.content == 'x\ty\rz\na'


class TestRepairArgumentsInPlace:
    def test_repairs_new_str_and_file_text(self) -> None:
        args = {
            'command': 'create_file',
            'path': 'index.html',
            'file_text': '<div class=\\"foo\\">\\n  hi\\n</div>',
            'insert_line': 0,
        }
        changes = repair_arguments_in_place(args, 'index.html')
        assert any(name == 'file_text' for name, _ in changes)
        assert args['file_text'] == '<div class="foo">\n  hi\n</div>'
        # non-content keys untouched
        assert args['command'] == 'create_file'
        assert args['insert_line'] == 0

    def test_no_changes_on_clean_args(self) -> None:
        args = {
            'file_text': '<div>\n  hi\n</div>\n',
            'new_str': 'x = 1\n',
        }
        changes = repair_arguments_in_place(args, 'a.html')
        assert changes == []

    def test_handles_missing_fields(self) -> None:
        changes = repair_arguments_in_place({}, 'index.html')
        assert changes == []
        changes = repair_arguments_in_place({'path': 'x.html'}, 'x.html')
        assert changes == []

    def test_known_content_names_contain_expected_keys(self) -> None:
        # Regression guard — these are the field names referenced by the
        # file-editor tool schema.
        for expected in ('file_text', 'new_str', 'section_content', 'patch_text'):
            assert expected in CONTENT_ARG_NAMES
