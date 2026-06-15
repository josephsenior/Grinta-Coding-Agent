"""GrintaScreen mixins — lifecycle, input, settings, etc."""

from backend.cli.tui.screen.actions import _AppScreenActionsMixin
from backend.cli.tui.screen.communicate import _AppScreenCommunicateMixin
from backend.cli.tui.screen.input import _AppScreenInputMixin
from backend.cli.tui.screen.lifecycle import _AppScreenLifecycleMixin
from backend.cli.tui.screen.messages import _AppScreenMessagesMixin
from backend.cli.tui.screen.settings import _AppScreenSettingsMixin
from backend.cli.tui.screen.state import _AppScreenStateMixin
from backend.cli.tui.screen.welcome import _AppScreenWelcomeMixin

__all__ = [
    '_AppScreenActionsMixin',
    '_AppScreenCommunicateMixin',
    '_AppScreenInputMixin',
    '_AppScreenLifecycleMixin',
    '_AppScreenMessagesMixin',
    '_AppScreenSettingsMixin',
    '_AppScreenStateMixin',
    '_AppScreenWelcomeMixin',
]
