"""Definition of the Orchestrator finish tool for signalling run completion."""

from backend.core.interaction_modes import PLAN_MODE, normalize_interaction_mode
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.inference.tool_names import FINISH_TOOL_NAME

_STATUS_PARAM = {
    'type': 'string',
    'enum': ['completed', 'blocked', 'failed'],
    'description': 'Run result status.',
}

_SUMMARY_PARAM = {
    'type': 'string',
    'description': (
        'Concise run summary for history/state. Keep it task-aware and factual: '
        'what outcome was reached, what matters for continuity, and any key '
        'constraints. 1-3 sentences.'
    ),
}

_RESPONSE_PARAM = {
    'type': 'string',
    'description': (
        'Polished user-facing final response in Markdown. Make it self-contained, '
        'specific, and shaped to the actual task. Do not force code-edit language '
        'onto non-code tasks.'
    ),
}

_SECTION_PARAM = {
    'type': 'array',
    'description': (
        'Consistent ordered content sections for the final answer. Use task-aware '
        'titles while preserving a comprehensive flow. Each section should have a '
        'short title and concrete items; use one item for a prose paragraph when '
        'a list would be unnatural.'
    ),
    'items': {
        'type': 'object',
        'properties': {
            'title': {
                'type': 'string',
                'description': 'Short section title, e.g. "Outcome", "Findings", "Recommended Plan", "Tradeoffs".',
            },
            'items': {
                'type': 'array',
                'description': 'Concrete bullets or compact paragraphs for this section.',
                'items': {'type': 'string'},
            },
        },
        'required': ['title', 'items'],
        'additionalProperties': False,
    },
}

_EVIDENCE_PARAM = {
    'type': 'object',
    'description': (
        'Evidence, verification, or confidence basis for the finish. For execution '
        'tasks, report actual validation. For planning/research/advice tasks, report '
        'the basis used or use not_applicable when proof does not apply.'
    ),
    'properties': {
        'status': {
            'type': 'string',
            'enum': [
                'passed',
                'failed',
                'partial',
                'not_run',
                'not_applicable',
                'planned',
            ],
        },
        'details': {
            'type': 'string',
            'description': (
                'Specific commands, checks, inspected sources, reasoning basis, or why '
                'verification was not run / not applicable.'
            ),
        },
    },
    'required': ['status', 'details'],
    'additionalProperties': False,
}

_OPEN_ITEMS_PARAM = {
    'type': 'array',
    'description': (
        'Open questions, remaining work, caveats, or blockers. Use an empty array '
        'when nothing material remains.'
    ),
    'items': {'type': 'string'},
}

_NEXT_STEP_PARAM = {
    'type': 'string',
    'description': 'Useful next step for the user, or an empty string when none is needed.',
}

_PLAN_FINISH_DESCRIPTION = (
    'Finish a Plan Mode run with a consistent, task-aware plan result. Plan Mode is codebase read-only; '
    'task tracking and communicate_with_user are allowed before finishing. Use blocked only '
    'when planning cannot continue. The response should read naturally to the user; '
    'sections should usually cover objective, recommended plan, scope/targets, '
    'risks/tradeoffs, verification strategy, and assumptions/open questions.'
)

_AGENT_FINISH_DESCRIPTION = (
    'Finish an Agent Mode execution run with a consistent, task-aware result. '
    'The response should deliver the outcome the user needs; sections should make '
    'the result comprehensive without forcing every task into a code-change report. '
    'Be honest about evidence/verification; if no validation was run, say so explicitly.'
)


def _create_plan_finish_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=FINISH_TOOL_NAME,
        description=_PLAN_FINISH_DESCRIPTION,
        properties={
            'status': _STATUS_PARAM,
            'response': _RESPONSE_PARAM,
            'summary': _SUMMARY_PARAM,
            'sections': _SECTION_PARAM,
            'evidence': _EVIDENCE_PARAM,
            'open_items': _OPEN_ITEMS_PARAM,
            'next_step': _NEXT_STEP_PARAM,
            'plan': {
                'type': 'array',
                'description': (
                    'Compatibility alias for plan steps. Prefer sections with a '
                    '"Recommended Plan" title. '
                    'Ordered list of concrete execution steps. Each step should start '
                    'with a verb, name the target file/path/symbol where known, and '
                    'explain the change or investigation to perform. Avoid vague items '
                    'like "fix bug" or "update code".'
                ),
                'items': {'type': 'string'},
            },
            'files_or_areas': {
                'type': 'array',
                'description': (
                    'Compatibility alias for scope/targets. Prefer sections with a '
                    '"Scope / Targets" title. '
                    'Relevant files, directories, symbols, features, routes, or config '
                    'areas the plan expects to touch or inspect. Use exact paths when known. '
                ),
                'items': {'type': 'string'},
            },
            'risks': {
                'type': 'array',
                'description': (
                    'Compatibility alias for risks/tradeoffs. Prefer sections. '
                    'Known risks, edge cases, migration concerns, compatibility concerns, '
                    'or parts needing care. Use an empty array only when there are truly no '
                    'material risks.'
                ),
                'items': {'type': 'string'},
            },
            'verification': {
                'type': 'array',
                'description': (
                    'Compatibility alias for verification strategy. Prefer evidence plus '
                    'a "Verification Strategy" section. '
                    'Specific verification steps for Agent Mode after implementation. Include '
                    'test/lint/typecheck commands, manual checks, or targeted repro steps. '
                ),
                'items': {'type': 'string'},
            },
            'assumptions': {
                'type': 'array',
                'description': (
                    'Compatibility alias for assumptions/open questions. Prefer sections '
                    'and open_items. '
                    'Assumptions made while producing the plan. Be specific '
                    'about dependencies, risks, version requirements, or '
                    'environment expectations (e.g. "Assumes PostgreSQL 15+ '
                    'with pgcrypto extension installed").'
                ),
                'items': {'type': 'string'},
            },
        },
        required=[
            'status',
            'response',
            'summary',
            'sections',
            'evidence',
            'open_items',
            'next_step',
        ],
    )


def _create_agent_finish_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=FINISH_TOOL_NAME,
        description=_AGENT_FINISH_DESCRIPTION,
        properties={
            'status': _STATUS_PARAM,
            'response': _RESPONSE_PARAM,
            'summary': _SUMMARY_PARAM,
            'sections': _SECTION_PARAM,
            'evidence': _EVIDENCE_PARAM,
            'open_items': _OPEN_ITEMS_PARAM,
            'next_step': _NEXT_STEP_PARAM,
            'actions_taken': {
                'type': 'array',
                'description': (
                    'Compatibility alias for performed work. Prefer sections with '
                    '"What I Did", "Outcome", or another task-aware title. '
                    'Concrete actions performed during execution. Each item should '
                    'include the file path and what was done (e.g. "Added input '
                    'validation to src/api/login.py"). Be specific — include '
                    'function names, routes, or config keys where relevant.'
                ),
                'items': {'type': 'string'},
            },
            'verification': {
                'type': 'object',
                'description': (
                    'Compatibility alias for evidence. Prefer evidence. '
                    'Validation results. Describe exactly what was verified — '
                    'specific commands run, pages visited, test suites executed, '
                    'or manual checks performed. Do not claim tests were run '
                    'unless they were.'
                ),
                'properties': {
                    'status': {
                        'type': 'string',
                        'enum': ['passed', 'failed', 'not_run', 'partial'],
                    },
                    'details': {
                        'type': 'string',
                        'description': (
                            'Specific validation performed. Include commands, '
                            'URLs visited, test names, or why validation was '
                            'not run / only partial.'
                        ),
                    },
                },
                'required': ['status', 'details'],
                'additionalProperties': False,
            },
            'remaining_items': {
                'type': 'array',
                'description': (
                    'Compatibility alias for open_items. Prefer open_items. '
                    'Known remaining work, if any. Be specific about what '
                    'is left undone and why (e.g. "Add rate limiting to '
                    'src/api/users.py — low priority, deferred").'
                ),
                'items': {'type': 'string'},
            },
            'lessons_learned': {
                'type': 'string',
                'description': (
                    'Optional internal reflection on recurring patterns, '
                    'mistakes, or verified solutions that should be remembered '
                    'for future tasks. Include specific anti-patterns, '
                    'solutions found, or configuration gotchas.'
                ),
            },
        },
        required=[
            'status',
            'response',
            'summary',
            'sections',
            'evidence',
            'open_items',
            'next_step',
        ],
    )


def create_finish_tool(mode: str = 'agent') -> ChatCompletionToolParam:
    """Create the mode-aware finish tool for the Orchestrator agent."""
    if normalize_interaction_mode(mode) == PLAN_MODE:
        return _create_plan_finish_tool()
    return _create_agent_finish_tool()
