"""CLI frontend — confirmation."""

from backend.tests.unit.cli.frontend import _shared
from backend.tests.unit.cli.frontend._shared import *  # noqa: F403
for _name in dir(_shared):
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = getattr(_shared, _name)

def test_confirmation_uses_backend_security_risk() -> None:
    action = CmdRunAction(command='echo hello')
    action.security_risk = ActionSecurityRisk.HIGH

    assert _risk_label(action) == ('HIGH', 'bold #fd8383')

def test_confirmation_handles_all_risk_levels() -> None:
    """All ActionSecurityRisk levels should map to readable labels."""
    for risk_val, expected_label in [
        (ActionSecurityRisk.HIGH, 'HIGH'),
        (ActionSecurityRisk.MEDIUM, 'MEDIUM'),
        (ActionSecurityRisk.LOW, 'LOW'),
        (ActionSecurityRisk.UNKNOWN, 'ASK'),
    ]:
        action = CmdRunAction(command='test')
        action.security_risk = risk_val
        label, _ = _risk_label(action)
        assert label == expected_label
