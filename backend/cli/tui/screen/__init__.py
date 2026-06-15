"""GrintaScreen mixins — lifecycle, input, settings, etc."""

from backend.cli.tui.screen.actions import ScreenActionsMixin
from backend.cli.tui.screen.communicate import ScreenCommunicateMixin
from backend.cli.tui.screen.input import ScreenInputMixin
from backend.cli.tui.screen.lifecycle import ScreenLifecycleMixin
from backend.cli.tui.screen.messages import ScreenMessagesMixin
from backend.cli.tui.screen.settings import ScreenSettingsMixin
from backend.cli.tui.screen.state import ScreenStateMixin
from backend.cli.tui.screen.welcome import ScreenWelcomeMixin

__all__ = [
    'ScreenActionsMixin',
    'ScreenCommunicateMixin',
    'ScreenInputMixin',
    'ScreenLifecycleMixin',
    'ScreenMessagesMixin',
    'ScreenSettingsMixin',
    'ScreenStateMixin',
    'ScreenWelcomeMixin',
]
