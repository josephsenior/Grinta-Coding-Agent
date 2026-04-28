"""Shared helper operations for the runtime action execution server."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast


def _aes_module():
    from backend.execution import action_execution_server as aes

    return aes


def init_shell_commands(executor: Any) -> None:
    aes = _aes_module()
    shell_session = executor.session_manager.get_session('default')
    assert shell_session is not None

    use_powershell = executor._uses_powershell_shell_contract()

    shell_session.execute(
        aes.CmdRunAction(
            command=executor._build_shell_git_config_command(use_powershell),
        )
    )

    shell_session.execute(
        aes.CmdRunAction(command=executor._build_env_check_command(use_powershell))
    )

    for plugin in executor.plugins.values():
        init_cmds = plugin.get_init_bash_commands()
        if init_cmds:
            for cmd in init_cmds:
                shell_session.execute(aes.CmdRunAction(command=cmd))


def build_shell_git_config_command(executor: Any, use_powershell: bool) -> str:
    separator = ';' if use_powershell else '&&'
    return (
        f'git config --global user.name "{executor.username}" '
        f'{separator} git config --global user.email "{executor.username}@example.com"'
    )


def build_env_check_command(use_powershell: bool) -> str:
    if use_powershell:
        return (
            "function global:env_check { "
            "Write-Output '=== PYTHON ==='; "
            "if (Get-Command python -ErrorAction SilentlyContinue) { python --version } "
            "elseif (Get-Command python3 -ErrorAction SilentlyContinue) { python3 --version } "
            "else { Write-Output 'python not found' }; "
            "Write-Output '=== KEY PACKAGES ==='; "
            "if (Get-Command pip -ErrorAction SilentlyContinue) { "
            "pip list --format=freeze | Select-Object -First 30 "
            "}; "
            "Write-Output '=== DISK ==='; "
            "Get-PSDrive -PSProvider FileSystem; "
            "Write-Output '=== MEMORY ==='; "
            "if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) { "
            "Get-CimInstance Win32_OperatingSystem | Select-Object "
            "@{Name='FreeMemoryMB';Expression={[math]::Round($_.FreePhysicalMemory / 1024, 1)}}, "
            "@{Name='TotalMemoryMB';Expression={[math]::Round($_.TotalVisibleMemorySize / 1024, 1)}} "
            "} "
            "}"
        )

    return (
        "alias env_check='"
        'echo "=== PYTHON ===" && python3 --version 2>/dev/null || python --version 2>/dev/null && '
        'echo "=== KEY PACKAGES ===" && pip list --format=freeze 2>/dev/null | head -30 && '
        'echo "=== DISK ===" && df -h . 2>/dev/null && '
        'echo "=== MEMORY ===" && free -h 2>/dev/null || vm_stat 2>/dev/null; '
        "true'"
    )


def uses_powershell_shell_contract(executor: Any) -> bool:
    aes = _aes_module()
    if not aes.OS_CAPS.is_windows:
        return False

    tool_registry = getattr(executor.session_manager, 'tool_registry', None)
    if tool_registry is not None:
        from backend.execution.utils.tool_registry import (
            resolve_windows_powershell_preference,
        )

        has_bash_raw = getattr(tool_registry, 'has_bash', False)
        has_powershell_raw = getattr(tool_registry, 'has_powershell', False)
        has_bash = has_bash_raw if isinstance(has_bash_raw, bool) else False
        has_powershell = (
            has_powershell_raw if isinstance(has_powershell_raw, bool) else False
        )

        if has_bash or has_powershell:
            return resolve_windows_powershell_preference(
                has_bash=has_bash,
                has_powershell=has_powershell,
            )

    default_session = executor.session_manager.get_session('default')
    session_name = default_session.__class__.__name__.lower() if default_session else ''
    return 'powershell' in session_name


def strip_ansi_obs_text(text: str) -> str:
    aes = _aes_module()
    if not text:
        return text
    return aes._ANSI_ESCAPE_RE.sub('', text)


def should_rewrite_python3_to_python(executor: Any) -> bool:
    return executor._uses_powershell_shell_contract()


def extract_failure_signature(content: str) -> str:
    if not content:
        return ''
    lines = [line.strip().lower() for line in content.splitlines() if line.strip()]
    if not lines:
        return ''
    return ' | '.join(lines[-3:])[:300]


def workspace_root(executor: Any) -> Path:
    return Path(executor._initial_cwd).resolve()


def is_workspace_restricted_profile(executor: Any) -> bool:
    aes = _aes_module()
    return aes.is_workspace_restricted_profile(executor.security_config)


def is_sandboxed_local(executor: Any) -> bool:
    aes = _aes_module()
    return aes.is_sandboxed_local_profile(executor.security_config)


def validate_interactive_session_scope(
    executor: Any, session_id: str, session: Any
) -> Any:
    aes = _aes_module()
    if not executor._is_workspace_restricted_profile():
        return None

    current_cwd = Path(getattr(session, 'cwd', executor._initial_cwd)).resolve()
    if aes.path_is_within_workspace(current_cwd, executor._workspace_root()):
        return None

    executor.session_manager.close_session(session_id)
    executor._clear_terminal_read_cursor(session_id)
    return aes.ErrorObservation(
        content=(
            'Interactive terminal session closed by hardened_local policy: '
            f'session cwd escaped the workspace. Session: {session_id} | cwd={current_cwd}'
        )
    )


def predict_interactive_cwd_change(
    executor: Any, command: str, current_cwd: Path
) -> tuple[Path | None, str | None]:
    aes = _aes_module()
    tokens = aes.tokenize_command(command)
    if not tokens:
        return (None, None)

    op = tokens[0].strip().lower()
    if op not in {'cd', 'pushd', 'set-location', 'sl'}:
        return (None, None)

    if len(tokens) < 2 or tokens[1].strip() in {'', '~', '$HOME', '%USERPROFILE%', '-'}:
        return (
            None,
            'Action blocked by hardened_local policy: interactive directory changes must target an explicit path inside the workspace.',
        )

    target = Path(tokens[1])
    predicted = target.resolve() if target.is_absolute() else (current_cwd / target).resolve()
    if not aes.path_is_within_workspace(predicted, executor._workspace_root()):
        return (
            None,
            'Action blocked by hardened_local policy: interactive terminal sessions cannot change directory outside the workspace. '
            f'Requested cwd: {predicted}',
        )
    return (predicted, None)


def evaluate_interactive_terminal_command(
    executor: Any, command: str, current_cwd: Path
) -> tuple[Path | None, Any]:
    aes = _aes_module()
    if not executor._is_workspace_restricted_profile():
        return (None, None)

    stripped = command.strip()
    if not stripped:
        return (None, None)

    if any(separator in stripped for separator in ('\n', '&&', ';', '||')):
        return (
            None,
            aes.ErrorObservation(
                content='Action blocked by hardened_local policy: interactive terminal input cannot contain chained or multiline commands.'
            ),
        )

    block_message = aes.evaluate_hardened_local_command_policy(
        command=stripped,
        security_config=executor.security_config,
        workspace_root=executor._workspace_root(),
        requested_cwd=str(current_cwd),
        base_cwd=str(current_cwd),
        is_background=stripped.endswith('&'),
    )
    if block_message is not None:
        return (None, aes.ErrorObservation(content=block_message))

    predicted_cwd, cwd_error = executor._predict_interactive_cwd_change(
        stripped, current_cwd
    )
    if cwd_error is not None:
        return (None, aes.ErrorObservation(content=cwd_error))

    return (predicted_cwd, None)


def resolve_effective_cwd(
    executor: Any, requested_cwd: str | None, base_cwd: str | None = None
) -> Path:
    root = executor._workspace_root()
    base_path = Path(base_cwd).resolve() if base_cwd else root
    if not requested_cwd:
        return base_path
    requested = Path(requested_cwd)
    if requested.is_absolute():
        return requested.resolve()
    return (base_path / requested).resolve()


def validate_workspace_scoped_cwd(
    executor: Any,
    command: str,
    requested_cwd: str | None,
    base_cwd: str | None = None,
) -> Any:
    aes = _aes_module()
    if not executor._is_workspace_restricted_profile():
        return None

    root = executor._workspace_root()
    effective_cwd = executor._resolve_effective_cwd(requested_cwd, base_cwd)
    try:
        effective_cwd.relative_to(root)
    except ValueError:
        return aes.ErrorObservation(
            content=(
                'Action blocked by hardened_local policy: command execution must stay inside the workspace. '
                f'Command: {command} | cwd={effective_cwd}'
            )
        )
    return None


def resolve_workspace_file_path(executor: Any, path: str, working_dir: str) -> str:
    aes = _aes_module()
    return str(aes.resolve_workspace_path(path, working_dir, executor._initial_cwd))


def annotate_environment_errors(executor: Any, observation: Any) -> None:
    content = observation.content
    if not content:
        return

    exit_code = int(getattr(observation.metadata, 'exit_code', 0) or 0)
    if exit_code == 0:
        return

    shell_mismatch = executor._detect_powershell_in_bash_mismatch(
        getattr(observation, 'command', ''),
        content,
    )
    if shell_mismatch:
        observation.content += f'\n\n[SHELL_MISMATCH] {shell_mismatch}'
        return

    scaffold_failure = executor._detect_scaffold_setup_failure(
        getattr(observation, 'command', ''),
        content,
    )
    if scaffold_failure:
        observation.content += f'\n\n[SCAFFOLD_SETUP_FAILED] {scaffold_failure}'


def _looks_like_bash_command_failure(content: str) -> bool:
    lower_content = content.lower()
    return (
        ('/bin/bash' in lower_content or 'bash:' in lower_content)
        and (
            'command not found' in lower_content
            or 'not recognized as' in lower_content
        )
    )


def _powershell_cmdlet_hint(cmdlet: str) -> str:
    bash_fix = (
        'This terminal is Git Bash — rewrite the command using bash syntax only '
        '(ls, cat, grep, find, echo, cd, mkdir, rm, pwd). '
        'Do NOT use any PowerShell cmdlets.'
    )
    return f'`{cmdlet}` is a PowerShell cmdlet, not available in bash. {bash_fix}'


def _missing_bash_command_name(content: str) -> str | None:
    missing_match = re.search(
        r'([A-Za-z][A-Za-z0-9-]*)\s*:\s*command not found', content
    )
    if not missing_match:
        return None
    return missing_match.group(1)


def _powershell_cmdlet_in_command(aes: Any, command: str) -> str | None:
    command_tokens = set(re.findall(r'\b[A-Za-z][A-Za-z0-9-]*\b', command))
    for token in aes._POWERSHELL_BUILTIN_COMMANDS:
        if token in command_tokens:
            return token
    return None


def detect_powershell_in_bash_mismatch(command: str, content: str) -> str | None:
    aes = _aes_module()
    if not command or not content:
        return None

    if not _looks_like_bash_command_failure(content):
        return None

    missing_cmd = _missing_bash_command_name(content)
    if missing_cmd in aes._POWERSHELL_BUILTIN_COMMANDS:
        return _powershell_cmdlet_hint(missing_cmd)

    command_cmdlet = _powershell_cmdlet_in_command(aes, command)
    if command_cmdlet is not None:
        return _powershell_cmdlet_hint(command_cmdlet)

    return None


def detect_scaffold_setup_failure(command: str, content: str) -> str | None:
    if not command or not content:
        return None

    lower_command = command.lower()
    if '&&' not in lower_command:
        return None

    scaffold_tokens = (
        'create-vite',
        'npm create',
        'npm create vite',
        'npm init vite',
        'create-next-app',
        'create-react-app',
        'cargo new',
    )
    if not any(token in lower_command for token in scaffold_tokens):
        return None

    lower_content = content.lower()
    if 'could not read package.json' not in lower_content:
        return None
    if 'enoent' in lower_content or 'no such file or directory' in lower_content:
        return (
            'The scaffold step did not create a project before follow-up install commands ran. '
            'Run the generator by itself first, inspect its output, and if the current directory '
            'is not empty scaffold into a fresh subdirectory instead of ".".'
        )
    return None


def apply_grep_filter(content: str, pattern_str: str) -> str:
    aes = _aes_module()
    pattern, err = aes.try_compile_user_regex(pattern_str)
    if pattern is None:
        return f"[Grep Error: Invalid regex pattern '{pattern_str}': {err}]\n{content}"

    lines = content.splitlines()
    filtered = [line for line in lines if pattern.search(line)]
    result = '\n'.join(filtered)
    return result or f"[Grep: No lines matched pattern '{pattern_str}']"


def attach_detected_server(executor: Any, observation: Any, bash_session: Any) -> None:
    aes = _aes_module()
    if bash_session is None:
        return
    detected = cast(Any, bash_session.get_detected_server())
    if not detected:
        return
    aes.logger.info('🚀 Adding detected server to observation extras: %s', detected.url)
    if not hasattr(observation, 'extras'):
        observation.extras = {}  # type: ignore[attr-defined]
    observation.extras['server_ready'] = {  # type: ignore[attr-defined]
        'port': detected.port,
        'url': detected.url,
        'protocol': detected.protocol,
        'health_status': detected.health_status,
    }


def apply_terminal_resize_if_requested(
    executor: Any, session: Any, rows: int | None, cols: int | None
) -> Any:
    aes = _aes_module()
    if rows is None and cols is None:
        return None
    if rows is None or cols is None:
        return aes.ErrorObservation(
            'Terminal resize requires both `rows` and `cols` (or omit both).'
        )
    r, c = int(rows), int(cols)
    if not (1 <= r <= 500 and 1 <= c <= 2000):
        return aes.ErrorObservation(
            f'Invalid terminal size: rows={r}, cols={c} '
            '(allowed: rows 1–500, cols 1–2000).'
        )
    try:
        session.resize(r, c)
    except Exception as exc:
        aes.logger.debug('Terminal resize not applied: %s', exc)
    return None


def next_terminal_session_id(executor: Any) -> str:
    sessions_obj = getattr(executor.session_manager, 'sessions', None)
    existing_ids = set(sessions_obj.keys()) if isinstance(sessions_obj, dict) else set()
    while True:
        executor._terminal_session_seq += 1
        candidate = f'terminal_{executor._terminal_session_seq}'
        if candidate not in existing_ids:
            return candidate


def normalize_terminal_command(command: str) -> str:
    return ' '.join((command or '').strip().lower().split())


def mark_terminal_session_interaction(executor: Any, session_id: str) -> None:
    if session_id in executor._terminal_sessions_awaiting_interaction:
        executor._terminal_sessions_awaiting_interaction = [
            sid
            for sid in executor._terminal_sessions_awaiting_interaction
            if sid != session_id
        ]
    executor._terminal_open_commands_no_interaction.clear()


def terminal_open_guardrail_error(executor: Any, command: str) -> Any:
    aes = _aes_module()
    pending = list(executor._terminal_sessions_awaiting_interaction)
    if len(pending) < 3:
        return None

    normalized = executor._normalize_terminal_command(command)
    recent = executor._terminal_open_commands_no_interaction[-3:]
    repetitive = bool(recent) and all(c == normalized for c in recent)

    if not repetitive and len(pending) < 6:
        return None

    sample_ids = ', '.join(pending[:8]) if pending else 'none'
    return aes.ErrorObservation(
        'terminal_manager open loop detected: multiple sessions were opened but '
        'none were used via action=read or action=input. '
        f'Current command={command!r}. '
        f'Use one of these existing session_id values next: {sample_ids}.'
    )


def missing_terminal_session_error(
    executor: Any, session_id: str, *, operation: str
) -> Any:
    aes = _aes_module()
    sessions_obj = getattr(executor.session_manager, 'sessions', None)
    active_ids = (
        sorted(k for k in sessions_obj if k != 'default')
        if isinstance(sessions_obj, dict)
        else []
    )
    if active_ids:
        suggestion = (
            f"Active session IDs: {', '.join(active_ids[:8])}. "
            'Use one returned by terminal_manager action=open.'
        )
    else:
        suggestion = (
            'No active terminal sessions exist right now. '
            'Call terminal_manager with action=open first, then reuse that session_id.'
        )
    return aes.ErrorObservation(
        f"Terminal session '{session_id}' does not exist for action={operation}. "
        f'Do not invent IDs like terminal_session_0. {suggestion}'
    )


def terminal_mode(mode: str | None) -> str:
    normalized = (mode or 'delta').strip().lower()
    if normalized not in {'delta', 'snapshot'}:
        return 'delta'
    return normalized


def terminal_read_empty_hints(*, mode: str, has_new_output: bool) -> dict[str, Any]:
    if has_new_output:
        return {}
    if mode == 'delta':
        return {
            'delta_empty': True,
            'empty_reason': 'no_new_bytes_since_offset',
        }
    return {
        'snapshot_empty': True,
        'empty_reason': 'no_printable_output_in_buffer',
    }


def _snapshot_terminal_read(session: Any) -> tuple[str, int | None, bool, int | None]:
    content = session.read_output()
    has_new_output = bool((content or '').strip())
    return content, None, has_new_output, None


def _fallback_terminal_delta_read(session: Any) -> tuple[str, int, int | None]:
    content = session.read_output()
    return content, len(content or ''), None


def _delta_terminal_read(
    session: Any,
    *,
    offset: int | None,
) -> tuple[str, int | None, bool, int | None]:
    safe_offset = max(0, int(offset or 0))
    read_since = getattr(session, 'read_output_since', None)
    if callable(read_since):
        try:
            result = read_since(safe_offset)
            if isinstance(result, tuple) and len(result) == 3 and isinstance(result[0], str):
                content, next_offset, dropped_chars = result
                return content, int(next_offset), bool(content), dropped_chars
            raise ValueError('invalid read_output_since result shape')
        except Exception:
            pass
    content, next_offset, dropped_chars = _fallback_terminal_delta_read(session)
    return content, int(next_offset), bool(content), dropped_chars


def read_terminal_with_mode(
    executor: Any,
    *,
    session: Any,
    mode: str,
    offset: int | None,
) -> tuple[str, int | None, bool, int | None]:
    if mode == 'snapshot':
        return _snapshot_terminal_read(session)
    return _delta_terminal_read(session, offset=offset)


def get_terminal_read_cursor(executor: Any, session_id: str) -> int:
    return int(executor._terminal_read_cursor.get(session_id, 0))


def advance_terminal_read_cursor(
    executor: Any,
    session_id: str,
    next_offset: int | None,
    *,
    mode: str = 'delta',
) -> None:
    if (mode or '').lower() != 'delta' or next_offset is None:
        return
    executor._terminal_read_cursor[session_id] = int(next_offset)


def clear_terminal_read_cursor(executor: Any, session_id: str) -> None:
    executor._terminal_read_cursor.pop(session_id, None)


def resolve_path(executor: Any, path: str, working_dir: str) -> str:
    return executor._resolve_workspace_file_path(path, working_dir)


def handle_aci_file_read(executor: Any, action: Any) -> Any:
    aes = _aes_module()
    result_str, _ = aes.execute_file_editor(
        executor.file_editor,
        command='read_file',
        path=action.path,
        view_range=action.view_range,
    )
    return aes.FileReadObservation(
        content=result_str, path=action.path, impl_source=aes.FileReadSource.FILE_EDITOR
    )


def edit_try_directory_view(
    executor: Any, filepath: str, path_for_obs: str, action: Any
) -> Any:
    aes = _aes_module()
    try:
        if os.path.isdir(filepath) and (action.command == 'read_file' or not action.command):
            return aes.handle_directory_view(filepath, path_for_obs)
    except Exception:
        pass
    return None


def edit_via_file_editor(executor: Any, action: Any) -> Any:
    aes = _aes_module()
    command = action.command or 'write'
    enable_lint = executor._is_auto_lint_enabled()
    result_str, (old_content, new_content) = aes.execute_file_editor(
        executor.file_editor,
        command=command,
        path=action.path,
        file_text=action.file_text,
        view_range=action.view_range,
        old_str=action.old_str,
        new_str=action.new_str,
        insert_line=action.insert_line,
        start_line=getattr(action, 'start_line', None),
        end_line=getattr(action, 'end_line', None),
        normalize_ws=action.normalize_ws,
        enable_linting=enable_lint,
        edit_mode=getattr(action, 'edit_mode', None),
        format_kind=getattr(action, 'format_kind', None),
        format_op=getattr(action, 'format_op', None),
        format_path=getattr(action, 'format_path', None),
        format_value=getattr(action, 'format_value', None),
        anchor_type=getattr(action, 'anchor_type', None),
        anchor_value=getattr(action, 'anchor_value', None),
        anchor_occurrence=getattr(action, 'anchor_occurrence', None),
        section_action=getattr(action, 'section_action', None),
        section_content=getattr(action, 'section_content', None),
        patch_text=getattr(action, 'patch_text', None),
        expected_hash=getattr(action, 'expected_hash', None),
        expected_file_hash=getattr(action, 'expected_file_hash', None),
    )
    if result_str.startswith('ERROR:'):
        return aes.ErrorObservation(result_str)
    max_chars = aes.get_max_edit_observation_chars()
    result_str = aes.truncate_large_text(result_str, max_chars, label='edit')
    if old_content is not None and new_content is not None and command != 'read_file':
        try:
            diff = aes.get_diff(old_content, new_content, action.path)
            if diff:
                result_str = result_str + '\n\n[EDIT_DIFF]\n' + diff
        except Exception:
            pass
    result_str = executor._append_blast_radius_warning(
        result_str,
        command=command,
        action_path=action.path,
        new_content=new_content,
    )

    return aes.FileEditObservation(
        content=result_str,
        path=action.path,
        prev_exist=old_content is not None,
        old_content=old_content,
        new_content=new_content,
        impl_source=aes.FileEditSource.FILE_EDITOR,
    )


def append_blast_radius_warning(
    executor: Any,
    base_content: str,
    *,
    command: str,
    action_path: str,
    new_content: str | None,
) -> str:
    aes = _aes_module()
    if command == 'read_file' or new_content is None:
        return base_content
    try:
        from backend.utils.blast_radius import check_blast_radius_from_code

        warning = check_blast_radius_from_code(action_path, new_content)
        if warning:
            return base_content + warning
    except Exception as exc:
        aes.logger.debug('Failed to check blast radius: %s', exc)
    return base_content


def is_auto_lint_enabled(executor: Any) -> bool:
    return os.environ.get('ENABLE_AUTO_LINT', '').lower() in {'1', 'true', 'yes'}