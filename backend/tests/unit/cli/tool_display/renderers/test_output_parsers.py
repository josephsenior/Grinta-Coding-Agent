import pytest
from backend.cli.tool_display.renderers.output_parsers import (
    parse_shell_output,
    ShellOutput,
    ParsedTestResult,
    ParsedGitStatus,
    ParsedLsOutput,
)

def test_parse_shell_output_pytest():
    stdout = """============================= test session starts ==============================
collected 3 items

test_sample.py .F.                                                       [100%]

=================================== FAILURES ===================================
_________________________________ test_fail __________________________________
    def test_fail():
>       assert False
E       assert False

=========================== short test summary info ============================
FAILED test_sample.py::test_fail - assert False
========================= 1 failed, 2 passed in 0.05s ==========================
"""
    result = parse_shell_output("pytest", stdout)
    assert result.kind == "pytest"
    assert result.parsed_test is not None
    assert result.parsed_test.passed == 2
    assert result.parsed_test.failed == 1
    assert result.parsed_test.has_failures is True



def test_parse_shell_output_ls():
    stdout = """total 12
drwxr-xr-x 2 user group 4096 Jul 17 12:00 dir1
-rw-r--r-- 1 user group  123 Jul 17 12:00 file1.txt
-rwxr-xr-x 1 user group 4567 Jul 17 12:00 script.sh
"""
    result = parse_shell_output("ls -la", stdout)
    assert result.kind == "ls"
    assert result.parsed_ls is not None
    assert len(result.parsed_ls.dirs) == 1
    assert len(result.parsed_ls.files) == 2

def test_parse_shell_output_plain():
    stdout = "Hello World\nThis is a test\n"
    result = parse_shell_output("echo", stdout)
    assert result.kind == "plain"
    assert len(result.lines) == 2
