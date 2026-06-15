"""Model-related error guidance rules."""

from __future__ import annotations

from backend.cli.event_rendering.error_categories.matchers import (
    _any,
    _budget_match,
    _context_size_match,
)
from backend.cli.event_rendering.panels import ErrorGuidance, _GuidanceRule

MODEL_GUIDANCE_RULES: tuple[_GuidanceRule, ...] = (
    _GuidanceRule(
        _any('404', 'model not found', 'does not exist', 'unknown model'),
        ErrorGuidance(
            summary='The configured model name is not available from the selected provider.',
            steps=(
                'Open /settings, press m, and pick a supported model.',
                'If you entered the model manually, include the correct provider prefix.',
            ),
            error_code='ERR-MODEL-001',
        ),
    ),
    _GuidanceRule(
        _context_size_match,
        ErrorGuidance(
            summary='The request is larger than the model can accept.',
            steps=(
                'Retry with a shorter prompt or less pasted context.',
                'If you need the larger context, switch models in /settings.',
            ),
            error_code='ERR-MODEL-002',
        ),
    ),
    _GuidanceRule(
        _budget_match,
        ErrorGuidance(
            summary='The task budget blocked another model call.',
            steps=(
                'Open /settings, press b, and raise the budget.',
                'Use 0 if you want to remove the per-task budget limit.',
                'Retry the request after saving the new budget.',
            ),
            error_code='ERR-MODEL-003',
        ),
    ),
)

__all__ = ['MODEL_GUIDANCE_RULES']
