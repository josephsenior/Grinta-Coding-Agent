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
        'Detailed summary of the run result. Cover what was accomplished, '
        'what changed (key files, functionality, config), and the end state. '
        'Include specific paths, feature names, or outcomes — 2-5 sentences.'
    ),
}

_NEXT_STEP_PARAM = {
    'type': 'string',
    'description': 'What should happen next.',
}

_PLAN_FINISH_DESCRIPTION = (
    'Finish a Plan Mode run with a structured execution plan. Plan Mode is read-only; '
    'use communicate_with_user for clarification before finishing. Use blocked only '
    'when planning cannot continue. '
    'Include a detailed summary covering what was investigated, what was found, '
    'and what the plan achieves. The plan should be concrete enough for Agent Mode '
    'to execute without rediscovering the whole task.'
)

_AGENT_FINISH_DESCRIPTION = (
    'Finish an Agent Mode execution run with a structured execution result. '
    'Provide a detailed summary covering what was accomplished, what changed, '
    'and the end state. Include specific file paths, feature names, and outcomes. '
    'Be honest about verification; if no validation was run, say so explicitly.'
)


def _create_plan_finish_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=FINISH_TOOL_NAME,
        description=_PLAN_FINISH_DESCRIPTION,
        properties={
            'status': _STATUS_PARAM,
            'summary': _SUMMARY_PARAM,
            'plan': {
                'type': 'array',
                'description': (
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
                    'Relevant files, directories, symbols, features, routes, or config '
                    'areas the plan expects to touch or inspect. Use exact paths when known. '
                    'For status="completed", include at least one item.'
                ),
                'items': {'type': 'string'},
            },
            'risks': {
                'type': 'array',
                'description': (
                    'Known risks, edge cases, migration concerns, compatibility concerns, '
                    'or parts needing care. Use an empty array only when there are truly no '
                    'material risks.'
                ),
                'items': {'type': 'string'},
            },
            'verification': {
                'type': 'array',
                'description': (
                    'Specific verification steps for Agent Mode after implementation. Include '
                    'test/lint/typecheck commands, manual checks, or targeted repro steps. '
                    'For status="completed", include at least one item.'
                ),
                'items': {'type': 'string'},
            },
            'assumptions': {
                'type': 'array',
                'description': (
                    'Assumptions made while producing the plan. Be specific '
                    'about dependencies, risks, version requirements, or '
                    'environment expectations (e.g. "Assumes PostgreSQL 15+ '
                    'with pgcrypto extension installed").'
                ),
                'items': {'type': 'string'},
            },
            'next_step': _NEXT_STEP_PARAM,
        },
        required=[
            'status',
            'summary',
            'plan',
            'files_or_areas',
            'risks',
            'verification',
            'assumptions',
            'next_step',
        ],
    )


def _create_agent_finish_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=FINISH_TOOL_NAME,
        description=_AGENT_FINISH_DESCRIPTION,
        properties={
            'status': _STATUS_PARAM,
            'summary': _SUMMARY_PARAM,
            'actions_taken': {
                'type': 'array',
                'description': (
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
                    'Known remaining work, if any. Be specific about what '
                    'is left undone and why (e.g. "Add rate limiting to '
                    'src/api/users.py — low priority, deferred").'
                ),
                'items': {'type': 'string'},
            },
            'next_step': _NEXT_STEP_PARAM,
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
            'summary',
            'actions_taken',
            'verification',
            'remaining_items',
            'next_step',
        ],
    )


def create_finish_tool(mode: str = 'agent') -> ChatCompletionToolParam:
    """Create the mode-aware finish tool for the Orchestrator agent."""
    if normalize_interaction_mode(mode) == PLAN_MODE:
        return _create_plan_finish_tool()
    return _create_agent_finish_tool()
