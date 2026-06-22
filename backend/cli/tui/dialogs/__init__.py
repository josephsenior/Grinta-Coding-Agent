"""TUI modal dialogs and inline confirmation widgets.

Import from this package root::

    from backend.cli.tui.dialogs import ConfirmWidget, GrintaSettingsDialog
"""

from backend.cli.tui.dialogs.add_mcp import GrintaAddMCPDialog
from backend.cli.tui.dialogs.add_skill import GrintaAddSkillDialog
from backend.cli.tui.dialogs.confirm import ConfirmWidget, GrintaConfirmDialog
from backend.cli.tui.dialogs.help import GrintaHelpDialog
from backend.cli.tui.dialogs.manage_mcp import GrintaManageMCPDialog
from backend.cli.tui.dialogs.manage_skills import GrintaManageSkillsDialog
from backend.cli.tui.dialogs.sessions import GrintaSessionsDialog
from backend.cli.tui.dialogs.settings import GrintaSettingsDialog

__all__ = [
    'ConfirmWidget',
    'GrintaAddMCPDialog',
    'GrintaAddSkillDialog',
    'GrintaConfirmDialog',
    'GrintaHelpDialog',
    'GrintaManageMCPDialog',
    'GrintaManageSkillsDialog',
    'GrintaSessionsDialog',
    'GrintaSettingsDialog',
]
