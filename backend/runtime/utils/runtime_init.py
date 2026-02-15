"""Initialization helpers for setting up runtime users and workspaces."""

from __future__ import annotations

import os
import subprocess
import sys

from backend.core.logger import FORGE_logger as logger


def _run_subprocess(
    command: list[str], *, log: bool = False
) -> subprocess.CompletedProcess[bytes]:
    """Helper to run subprocess commands with consistent parameters."""
    result = subprocess.run(command, check=False, shell=False, capture_output=True)
    if log:
        stdout = result.stdout.decode().strip()
        stderr = result.stderr.decode().strip()
        logger.debug(
            "Command %s returned %s – stdout: %s – stderr: %s",
            command,
            result.returncode,
            stdout,
            stderr,
        )
    return result


def init_user_and_working_directory(
    username: str, user_id: int, initial_cwd: str
) -> int | None:
    """Create working directory and user if not exists."""
    if _handle_windows_platform(initial_cwd):
        return None

    if _should_skip_user_setup(username):
        _prepare_working_directory(username, initial_cwd)
        return None

    if username != "root" and not _has_root_capabilities(username):
        return None

    existing_uid = _lookup_existing_user(username)
    if existing_uid is not None:
        if existing_uid == user_id:
            logger.debug(
                "User `%s` already has the provided UID %s. Skipping user setup.",
                username,
                user_id,
            )
            _prepare_working_directory(username, initial_cwd)
            return None

        logger.warning(
            "User `%s` already exists with UID %s. Skipping user setup.",
            username,
            existing_uid,
        )
        return existing_uid

    logger.debug("User `%s` does not exist. Proceeding with user creation.", username)
    _add_passwordless_sudo_entry()
    _create_user_account(username, user_id)
    _prepare_working_directory(username, initial_cwd)
    return None


def _handle_windows_platform(initial_cwd: str) -> bool:
    platform_name = getattr(sys, "platform")
    if platform_name != "win32":
        return False

    logger.debug("Running on Windows, skipping Unix-specific user setup")
    logger.debug("Client working directory: %s", initial_cwd)
    os.makedirs(initial_cwd, exist_ok=True)
    logger.debug("Created working directory: %s", initial_cwd)
    return True


def _should_skip_user_setup(username: str) -> bool:
    current_user = os.getenv("USER") or ""
    if username == current_user and username not in ["root", "forge"]:
        logger.debug(
            "User `%s` matches current user `%s`; skipping extra setup.",
            username,
            current_user,
        )
        return True
    return False


def _has_root_capabilities(username: str) -> bool:
    if not hasattr(os, "geteuid"):
        logger.warning(
            "Skipping user setup for `%s` because os.geteuid is unavailable on this platform.",
            username,
        )
        return False

    current_uid = _run_subprocess(["id", "-u"])
    if current_uid.returncode != 0 or current_uid.stdout.decode().strip() != "0":
        logger.warning(
            "Skipping user setup for `%s` because the current process lacks root privileges.",
            username,
        )
        return False

    return True


def _lookup_existing_user(username: str) -> int | None:
    logger.debug(
        "Attempting to create user `%s` – checking if it already exists.", username
    )
    result = _run_subprocess(["id", "-u", username])
    if result.returncode == 0:
        try:
            return int(result.stdout.decode().strip())
        except ValueError:
            logger.error(
                "Unexpected output when checking user `%s`: %s", username, result.stdout
            )
            raise

    if result.returncode == 1:
        return None

    logger.error(
        "Error checking user `%s`, skipping setup:\n%s\n", username, result.stderr
    )
    raise subprocess.CalledProcessError(
        result.returncode,
        result.args,
        output=result.stdout,
        stderr=result.stderr,
    )


def _add_passwordless_sudo_entry() -> None:
    sudoer_line = [
        "sh",
        "-c",
        "echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers",
    ]
    sudo_result = _run_subprocess(sudoer_line)
    if sudo_result.returncode != 0:
        logger.warning(
            "Failed to add sudoer entry: %s", sudo_result.stderr.decode().strip()
        )
    else:
        logger.debug(
            "Added sudoer successfully. Output: [%s]",
            sudo_result.stdout.decode().strip(),
        )


def _create_user_account(username: str, user_id: int) -> None:
    command = [
        "useradd",
        "-rm",
        "-d",
        f"/home/{username}",
        "-s",
        "/bin/bash",
        "-g",
        "root",
        "-G",
        "sudo",
        "-u",
        str(user_id),
        username,
    ]
    useradd_result = _run_subprocess(command)
    if useradd_result.returncode == 0:
        logger.debug(
            "Added user `%s` successfully with UID %s. Output: [%s]",
            username,
            user_id,
            useradd_result.stdout.decode().strip(),
        )
        return

    logger.warning(
        "Failed to create user `%s` with UID %s. Output: [%s]",
        username,
        user_id,
        useradd_result.stderr.decode().strip(),
    )


def _prepare_working_directory(username: str, initial_cwd: str) -> None:
    logger.debug("Client working directory: %s", initial_cwd)
    mkdir_cmd = ["sh", "-c", f"umask 002; mkdir -p {initial_cwd}"]
    chown_cmd = ["chown", "-R", f"{username}:root", initial_cwd]
    chmod_cmd = ["chmod", "g+rw", initial_cwd]

    out_str_parts: list[str] = []
    for cmd in (mkdir_cmd, chown_cmd, chmod_cmd):
        result = _run_subprocess(cmd)
        decoded = result.stdout.decode().strip()
        if decoded:
            out_str_parts.append(decoded)
        if result.returncode != 0:
            logger.warning(
                "Command %s exited with %s: %s",
                cmd,
                result.returncode,
                result.stderr.decode().strip(),
            )
    logger.debug("Created working directory. Output: [%s]", "\n".join(out_str_parts))
