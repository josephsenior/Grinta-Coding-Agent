from __future__ import annotations

from unittest.mock import patch

from backend.engine.tools.apply_patch import (
    build_apply_patch_action,
    create_apply_patch_tool,
)


class TestBuildApplyPatchAction:
    def test_uses_shell_safe_python_transport(self) -> None:
        with patch(
            'backend.engine.tools.apply_patch.build_python_exec_command',
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            action = build_apply_patch_action('diff --git a/x b/x')

        assert action.command == 'python3 -c "encoded"'
        script = mock_transport.call_args.args[0]
        assert 'NamedTemporaryFile' in script
        assert 'git_args' in script

    def test_command_hides_raw_patch_content(self) -> None:
        action = build_apply_patch_action('diff --git a/x b/x\n+print("hi")')

        assert 'b64decode' in action.command
        assert 'print("hi")' not in action.command
        assert action.thought == '[APPLY PATCH] applying patch'
        assert action.display_label == 'Applying patch'

    def test_check_only_uses_validating_display_label(self) -> None:
        action = build_apply_patch_action('diff --git a/x b/x', check_only=True)

        assert action.display_label == 'Validating patch'

    def test_tool_description_requires_full_git_unified_diff_headers(self) -> None:
        tool = create_apply_patch_tool()
        fn = tool['function']
        desc = fn['description']
        patch_desc = fn['parameters']['properties']['patch']['description']

        assert 'diff --git' in desc
        assert 'index <old_hash>..<new_hash> <mode>' in desc
        assert 'corrupt patch at line X' in desc
        assert 'patch does not apply' in desc
        assert 'Always generate patches via `git diff`' in desc
        assert 'diff --git' in patch_desc
        assert 'index' in patch_desc

    def test_script_contains_corrupt_patch_guidance(self) -> None:
        with patch(
            'backend.engine.tools.apply_patch.build_python_exec_command',
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action('diff --git a/x b/x')

        script = mock_transport.call_args.args[0]
        assert '[APPLY_PATCH_GUIDANCE]' in script
        assert '[APPLY_PATCH_STATS]' in script

    def test_script_escapes_newline_literals_for_generated_python(self) -> None:
        with patch(
            'backend.engine.tools.apply_patch.build_python_exec_command',
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action('diff --git a/x b/x')

        script = mock_transport.call_args.args[0]
        assert "+ '\\n' +" in script
        assert "+ '\\n\\n' + guidance" in script
