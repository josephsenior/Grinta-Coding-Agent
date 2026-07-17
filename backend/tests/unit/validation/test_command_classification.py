"""Tests for token-oriented command classification used by validation and stuck detection."""

from __future__ import annotations

from backend.ledger.action.commands import CmdRunAction
from backend.ledger.observation.commands import CmdOutputObservation
from backend.validation.command_classification import (
    classify_shell_intent,
    find_cmd_output_for_run,
    is_git_diff_command,
    is_test_run_command,
)


def test_is_test_run_command_pytest():
    assert is_test_run_command('pytest -q tests/unit') is True
    assert is_test_run_command('python -m pytest foo') is True


def test_is_test_run_command_npm():
    assert is_test_run_command('npm test') is True
    assert is_test_run_command('pnpm test --filter pkg') is True


def test_is_test_run_command_negative():
    assert is_test_run_command('echo testing things') is False


def test_is_git_diff_command():
    assert is_git_diff_command('git diff HEAD~1') is True
    assert is_git_diff_command('git show abc123') is True
    assert is_git_diff_command('ls') is False


def test_find_cmd_output_pairs_by_cause():
    run = CmdRunAction(command='pytest -q')
    run.id = 42
    obs = CmdOutputObservation(content='ok', command='pytest -q', exit_code=0)
    obs.cause = 42
    hist = [run, obs]
    paired = find_cmd_output_for_run(run, hist, 0)
    assert paired is obs


def test_find_cmd_output_skips_wrong_cause():
    run = CmdRunAction(command='pytest -q')
    run.id = 42
    noise = CmdOutputObservation(content='x', command='other', exit_code=1)
    noise.cause = 99
    obs = CmdOutputObservation(content='ok', command='pytest -q', exit_code=0)
    obs.cause = 42
    hist = [run, noise, obs]
    paired = find_cmd_output_for_run(run, hist, 0)
    assert paired is obs


def test_classify_shell_intent():
    assert classify_shell_intent('pytest -q') == 'run_test'
    assert classify_shell_intent('git diff') == 'inspect_git'
    assert classify_shell_intent('ls -la') == 'inspect_filesystem'


def test_argv_tokens_error_fallback():
    # Value error caused by unclosed quote falls back to split()
    assert classify_shell_intent('echo "hello') == 'other_command'


def test_is_test_run_command_varieties():
    # unittest module invocation
    assert is_test_run_command('python -m unittest') is True
    assert is_test_run_command('python3 -m unittest test_suite') is True
    assert is_test_run_command('-m unittest') is True
    
    # native and package managers
    assert is_test_run_command('cargo test') is True
    assert is_test_run_command('go test ./...') is True
    assert is_test_run_command('make test') is True
    assert is_test_run_command('make check') is True
    assert is_test_run_command('gradle test') is True
    assert is_test_run_command('mvn test') is True

    # Empty command string
    assert is_test_run_command('') is False
    assert is_test_run_command('   ') is False


def test_git_diff_command_edge_cases():
    assert is_git_diff_command('git') is False
    assert is_git_diff_command('git status') is False


def test_classify_non_test_shell_intents():
    # filesystem inspection
    assert classify_shell_intent('cat file.txt') == 'inspect_filesystem'
    assert classify_shell_intent('type file.txt') == 'inspect_filesystem'
    assert classify_shell_intent('get-content file.log') == 'inspect_filesystem'
    assert classify_shell_intent('get-childitem') == 'inspect_filesystem'
    
    # fetch code
    assert classify_shell_intent('git clone https://some-url') == 'fetch_code'
    assert classify_shell_intent('git pull origin main') == 'fetch_code'
    assert classify_shell_intent('git fetch') == 'fetch_code'

    # install dependencies
    assert classify_shell_intent('pip install requests') == 'install_dependency'
    assert classify_shell_intent('cargo build') == 'install_dependency'

    # file creation
    assert classify_shell_intent('mkdir my_folder') == 'create_file'
    assert classify_shell_intent('touch file.txt') == 'create_file'
    assert classify_shell_intent('echo "content" > file.txt') == 'create_file'

    # delete file
    assert classify_shell_intent('rm -rf file.txt') == 'delete_file'
    assert classify_shell_intent('del file.txt') == 'delete_file'
    assert classify_shell_intent('remove-item file.txt') == 'delete_file'

    # execute code
    assert classify_shell_intent('python script.py') == 'execute_code'
    assert classify_shell_intent('node app.js') == 'execute_code'


def test_find_cmd_output_no_event_id_fallback():
    # When CmdRunAction has no event ID, fall back to matching command string
    run = CmdRunAction(command='pytest -q')
    run.id = None  # No event ID
    
    obs = CmdOutputObservation(content='ok', command='pytest -q', exit_code=0)
    
    # Paired by matching command
    hist = [run, obs]
    paired = find_cmd_output_for_run(run, hist, 0)
    assert paired is obs


def test_find_cmd_output_no_event_id_fallback_mismatch():
    run = CmdRunAction(command='pytest -q')
    run.id = None
    
    # Mismatch command
    obs = CmdOutputObservation(content='ok', command='other-command', exit_code=0)
    
    hist = [run, obs]
    paired = find_cmd_output_for_run(run, hist, 0)
    assert paired is None

