from __future__ import annotations

from unittest.mock import patch

from backend.engine.tools.apply_patch import (
    build_apply_patch_action,
    create_apply_patch_tool,
    validate_apply_patch_contract,
)

_VALID_PATCH = (
    "diff --git a/x b/x\n"
    "index 1111111..2222222 100644\n"
    "--- a/x\n"
    "+++ b/x\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)

_VALID_PATCH_NO_INDEX = (
    "diff --git a/x b/x\n"
    "--- a/x\n"
    "+++ b/x\n"
    "@@ -1 +1 @@\n"
    "-old\n"
    "+new\n"
)


class TestBuildApplyPatchAction:
    def test_uses_shell_safe_python_transport(self) -> None:
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            action = build_apply_patch_action(_VALID_PATCH)

        assert action.command == 'python3 -c "encoded"'
        script = mock_transport.call_args.args[0]
        assert "NamedTemporaryFile" in script
        assert "git_args" in script

    def test_command_hides_raw_patch_content(self) -> None:
        action = build_apply_patch_action(
            "diff --git a/x b/x\n"
            "index 1111111..2222222 100644\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            '+print("hi")\n'
        )

        assert "b64decode" in action.command
        assert 'print("hi")' not in action.command
        assert action.thought == "[APPLY PATCH] applying patch"
        assert action.display_label == "Applying patch"

    def test_check_only_uses_validating_display_label(self) -> None:
        action = build_apply_patch_action(_VALID_PATCH, check_only=True)

        assert action.display_label == "Validating patch"

    def test_tool_description_requires_full_git_unified_diff_headers(self) -> None:
        tool = create_apply_patch_tool()
        fn = tool["function"]
        desc = fn["description"]
        patch_desc = fn["parameters"]["properties"]["patch"]["description"]

        assert "diff --git" in desc
        assert "Optional but validated when present" in desc
        assert "index <old_hash>..<new_hash> [mode]" in desc
        assert "malformed index line" in desc
        assert "patch does not apply" in desc
        assert "Always generate patches via `git diff`" in desc
        assert "diff --git" in patch_desc
        assert "Index line is optional" in patch_desc

    def test_script_contains_runtime_corrupt_patch_guidance(self) -> None:
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action(_VALID_PATCH)

        script = mock_transport.call_args.args[0]
        assert "[APPLY_PATCH_GUIDANCE]" in script
        assert "[APPLY_PATCH_STATS]" in script
        assert "import whatthepatch" in script
        assert "_apply_python_fallback" in script

    def test_script_fails_fast_for_invalid_patch_contract(self) -> None:
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            action = build_apply_patch_action(
                "diff --git a/x b/x\n"
                "index 0000..e69de29\n"
                "--- a/x\n"
                "+++ b/x\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            )

        script = mock_transport.call_args.args[0]
        assert action.display_label == "Applying patch"
        assert "[APPLY_PATCH_GUIDANCE]" in script
        assert "malformed index line" in script
        assert "NamedTemporaryFile" not in script
        assert "sys.exit(2)" in script

    def test_script_escapes_newline_literals_for_generated_python(self) -> None:
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action(_VALID_PATCH)

        script = mock_transport.call_args.args[0]
        assert "+ '\\n' +" in script
        assert "+ '\\n\\n' + guidance" in script


class TestValidateApplyPatchContract:
    def test_accepts_missing_index_line(self) -> None:
        assert validate_apply_patch_contract(_VALID_PATCH_NO_INDEX) is None

    def test_rejects_malformed_index_line(self) -> None:
        error = validate_apply_patch_contract(
            "diff --git a/x b/x\n"
            "index 0000..e69de29\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        assert error is not None
        assert "malformed index line" in error

    def test_accepts_index_without_mode(self) -> None:
        error = validate_apply_patch_contract(
            "diff --git a/new.txt b/new.txt\n"
            "new file mode 100644\n"
            "index 0000000..1111111\n"
            "--- /dev/null\n"
            "+++ b/new.txt\n"
            "@@ -0,0 +1 @@\n"
            "+hello\n"
        )

        assert error is None

    def test_accepts_canonical_patch(self) -> None:
        assert validate_apply_patch_contract(_VALID_PATCH) is None
