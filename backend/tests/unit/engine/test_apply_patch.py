from __future__ import annotations

import base64
import re
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
    "diff --git a/x b/x\n" "--- a/x\n" "+++ b/x\n" "@@ -1 +1 @@\n" "-old\n" "+new\n"
)


class TestBuildApplyPatchAction:
    def test_uses_shell_safe_python_transport(self) -> None:
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            action = build_apply_patch_action(
                _VALID_PATCH,
                last_verified_line_content="old",
            )

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
            '+print("hi")\n',
            last_verified_line_content="old",
        )

        assert "b64decode" in action.command
        assert 'print("hi")' not in action.command
        assert action.thought == "[APPLY PATCH] applying patch"
        assert action.display_label == "Applying patch"

    def test_check_only_uses_validating_display_label(self) -> None:
        action = build_apply_patch_action(
            _VALID_PATCH,
            check_only=True,
            last_verified_line_content="old",
        )

        assert action.display_label == "Validating patch"

    def test_tool_description_requires_full_git_unified_diff_headers(self) -> None:
        tool = create_apply_patch_tool()
        fn = tool["function"]
        desc = fn["description"]
        patch_desc = fn["parameters"]["properties"]["patch"]["description"]

        assert "diff --git" in desc
        assert "CRITICAL: Exact Format Required" in desc
        assert "@@" in desc
        assert "last_verified_line_content" in fn["parameters"]["properties"]
        assert "last_verified_line_content" in fn["parameters"]["required"]
        assert "diff --git" in patch_desc

    def test_script_contains_runtime_corrupt_patch_guidance(self) -> None:
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action(
                _VALID_PATCH,
                last_verified_line_content="old",
            )

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
                "--- wrong\n"
                "+++ b/x\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "+new\n"
            )

        script = mock_transport.call_args.args[0]
        assert action.display_label == "Applying patch"
        assert "[APPLY_PATCH_GUIDANCE]" in script
        assert "Malformed `---` header" in script
        assert "NamedTemporaryFile" not in script
        assert "sys.exit(2)" in script

    def test_script_escapes_newline_literals_for_generated_python(self) -> None:
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action(
                _VALID_PATCH,
                last_verified_line_content="old",
            )

        script = mock_transport.call_args.args[0]
        assert "+ '\\n' +" in script
        assert "\\n\\n{guidance}" in script

    def test_auto_appends_terminal_newline_to_patch_payload(self) -> None:
        patch_without_terminal_newline = (
            "diff --git a/x b/x\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new"
        )
        with patch(
            "backend.engine.tools.apply_patch.build_python_exec_command",
            return_value='python3 -c "encoded"',
        ) as mock_transport:
            build_apply_patch_action(
                patch_without_terminal_newline,
                last_verified_line_content="old",
            )

        script = mock_transport.call_args.args[0]
        encoded_match = re.search(r"base64\.b64decode\(b'([^']+)'\)", script)
        assert encoded_match is not None
        decoded_patch = base64.b64decode(encoded_match.group(1)).decode()
        assert decoded_patch.endswith("\n")


class TestValidateApplyPatchContract:
    def test_accepts_missing_index_line(self) -> None:
        assert validate_apply_patch_contract(
            _VALID_PATCH_NO_INDEX
        ) == _VALID_PATCH_NO_INDEX.rstrip("\n")

    def test_accepts_malformed_index_line(self) -> None:
        error = validate_apply_patch_contract(
            "diff --git a/x b/x\n"
            "index 0000..e69de29\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        assert error == _VALID_PATCH_NO_INDEX.rstrip("\n")

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

        assert error.startswith("diff --git a/new.txt b/new.txt")
        assert "@@ -0,0 +1 @@" in error

    def test_accepts_canonical_patch(self) -> None:
        normalized = validate_apply_patch_contract(_VALID_PATCH)
        assert normalized.startswith("diff --git a/x b/x")
        assert "index 1111111..2222222" not in normalized

    def test_rejects_malformed_hunk_line_counts(self) -> None:
        error = validate_apply_patch_contract(
            "diff --git a/x b/x\n"
            "--- a/x\n"
            "+++ b/x\n"
            "@@ -1,2 +1,1 @@\n"
            " old\n"
            "-old2\n"
            "+new\n"
        )

        assert error.startswith("Malformed hunk line counts")

    def test_rejects_malformed_minus_header(self) -> None:
        error = validate_apply_patch_contract(
            "diff --git a/x b/x\n"
            "--- wrong\n"
            "+++ b/x\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        assert "Malformed `---` header" in error
