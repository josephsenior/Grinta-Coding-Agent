import pytest
import os
from unittest.mock import patch, mock_open

from backend.execution.plugins.agent_skills.file_ops.file_ops import (
    _output_error,
    _is_valid_filename,
    _is_valid_path,
    _clamp,
    _check_current_file,
    open_file,
)

def test_output_error():
    assert _output_error("msg") == "ERROR: msg"

def test_is_valid_filename():
    assert _is_valid_filename("test.txt") is True
    assert _is_valid_filename("") is False
    assert _is_valid_filename(None) is False
    assert _is_valid_filename("invalid<char>.txt") is False

def test_is_valid_path():
    assert _is_valid_path(None) is False
    assert _is_valid_path("") is False
    
    with patch("os.path.exists", return_value=True):
        assert _is_valid_path("valid/path") is True

def test_clamp():
    assert _clamp(5, 1, 10) == 5
    assert _clamp(0, 1, 10) == 1
    assert _clamp(15, 1, 10) == 10

def test_check_current_file():
    with patch("backend.execution.plugins.agent_skills.file_ops.file_ops.CURRENT_FILE", None):
        assert _check_current_file() == "ERROR: No file open. Use the open_file function first."


