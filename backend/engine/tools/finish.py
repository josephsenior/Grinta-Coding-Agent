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
    'and what the plan achieves.'
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
                    'Ordered list of concrete execution steps. Each step should '
                    'include the file path(s) and what will be done (e.g. '
                    '"Add input validation to src/api/login.py"). Be specific '
                    'about functions, routes, or config keys to be modified.'
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
        required=['status', 'summary', 'plan', 'assumptions', 'next_step'],
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
