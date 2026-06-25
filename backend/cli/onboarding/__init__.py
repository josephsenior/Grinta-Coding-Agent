"""First-run onboarding: init wizard, connection check, and settings flow."""

from __future__ import annotations

from backend.cli.onboarding.connection_check import _test_llm_call
from backend.cli.onboarding.flow import (
    auto_detect_api_keys,
    needs_onboarding,
    persist_env_detected_settings,
    run_onboarding,
)

__all__ = [
    '_test_llm_call',
    'auto_detect_api_keys',
    'needs_onboarding',
    'persist_env_detected_settings',
    'run_onboarding',
]
