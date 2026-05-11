"""Desktop notifications for agent completion and input-needed events.

Cross-platform: Windows (PowerShell BurntToast / win32), macOS (osascript),
Linux (notify-send). Falls back silently when no notifier is available.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Env var to disable notifications entirely.
_GRINTA_NO_NOTIFY = {'1', 'true', 'yes', 'on'}


def _notifications_disabled() -> bool:
    return os.getenv('GRINTA_NO_NOTIFY', '').strip().lower() in _GRINTA_NO_NOTIFY


def notify(title: str, body: str, *, urgency: str = 'normal') -> None:
    """Fire a desktop notification. Best-effort, never raises.

    Parameters
    ----------
    title:
        Notification title (e.g. "Grinta — Task Complete").
    body:
        Notification body text.
    urgency:
        ``low``, ``normal``, or ``critical``.  Affects Linux hint; ignored elsewhere.
    """
    if _notifications_disabled():
        return
    try:
        _do_notify(title, body, urgency=urgency)
    except Exception:
        logger.debug('Desktop notification failed', exc_info=True)


def _do_notify(title: str, body: str, *, urgency: str) -> None:
    if os.name == 'nt':
        _notify_windows(title, body)
    elif shutil.which('osascript'):
        _notify_macos(title, body)
    elif shutil.which('notify-send'):
        _notify_linux(title, body, urgency=urgency)
    else:
        logger.debug('No notification backend available')


def _notify_windows(title: str, body: str) -> None:
    # Try PowerShell BurntToast first (Windows 10+ toast notifications).
    ps_cmd = (
        f"[Windows.UI.Notifications.ToastNotificationManager, "
        f"Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
        f"$template = [Windows.UI.Notifications.ToastNotificationManager]::"
        f"GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        f"$textNodes = $template.GetElementsByTagName('text'); "
        f"$textNodes.Item(0).AppendChild($template.CreateTextNode('{_ps_escape(title)}')) | Out-Null; "
        f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{_ps_escape(body)}')) | Out-Null; "
        f"$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
        f"[Windows.UI.Notifications.ToastNotificationManager]::"
        f"CreateToastNotifier('Grinta').Show($toast);"
    )
    try:
        subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps_cmd],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return
    except Exception:
        pass

    # Fallback: simple msg.exe (older Windows, less pretty).
    try:
        subprocess.run(
            ['msg', '*', f'/TIME:5', f'{title}: {body}'],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:
        pass


def _notify_macos(title: str, body: str) -> None:
    script = f'display notification "{_applescript_escape(body)}" with title "{_applescript_escape(title)}"'
    subprocess.run(
        ['osascript', '-e', script],
        capture_output=True,
        timeout=5,
        check=False,
    )


def _notify_linux(title: str, body: str, *, urgency: str) -> None:
    cmd = ['notify-send', f'--urgency={urgency}', '--app-name=Grinta', title, body]
    subprocess.run(cmd, capture_output=True, timeout=5, check=False)


def _ps_escape(s: str) -> str:
    """Escape a string for PowerShell single-quoted context."""
    return s.replace("'", "''")


def _applescript_escape(s: str) -> str:
    """Escape a string for AppleScript double-quoted context."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def notify_agent_idle(*, needs_input: bool = False) -> None:
    """Convenience: notify when the agent finishes a turn or needs input."""
    if needs_input:
        notify('Grinta — Input Needed', 'The agent is waiting for your response.', urgency='normal')
    else:
        notify('Grinta — Task Complete', 'The agent has finished processing.', urgency='low')


def notify_agent_error(summary: str = 'An error occurred during processing.') -> None:
    """Convenience: notify on agent error."""
    notify('Grinta — Error', summary, urgency='critical')
