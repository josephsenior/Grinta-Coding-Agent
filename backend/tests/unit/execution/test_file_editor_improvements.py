from backend.execution.utils.file_editor import FileEditor, ToolResult


def test_ws_tolerant_replace_failure_message_improved():
    fe = FileEditor()
    # Content with two simple functions
    content = (
        'def a():\n'
        '    return 1\n'
        '\n'
        'def b():\n'
        '    return 2\n'
    )

    # old_str not present; multi-line pattern
    old_str = (
        'def c():\n'
        '    return 3\n'
    )

    res = fe._apply_str_replace(content, old_str, 'REPLACED')
    assert isinstance(res, ToolResult)
    assert res.error is not None and res.error.strip() != ''
    # Ensure we don't return the vague legacy internal-failure message
    assert 'Whitespace-based matching failed internally.' not in (res.error or '')
