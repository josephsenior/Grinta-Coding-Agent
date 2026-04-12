from __future__ import annotations

from unittest.mock import patch

from backend.engine.tools.apply_patch import build_apply_patch_action


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

    def test_script_contains_corrupt_patch_guidance(self) -> None:
        with patch(
            'backend.engine.tools.apply_patch.build_python_exec_command',
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action('diff --git a/x b/x')

        script = mock_transport.call_args.args[0]
        assert '[APPLY_PATCH_GUIDANCE]' in script

    def test_script_escapes_newline_literals_for_generated_python(self) -> None:
        with patch(
            'backend.engine.tools.apply_patch.build_python_exec_command',
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action('diff --git a/x b/x')

        script = mock_transport.call_args.args[0]
        assert "+ '\\n' +" in script
        assert "+ '\\n\\n' + guidance" in script
