"""Constants and regex tables shared by event-renderer helpers."""

from __future__ import annotations

import re

# -- Reasoning / thought sanitisation ----------------------------------------

# Matches both <redacted_thinking> (Anthropic/MiniMax) and <think> (DeepSeek
# R1, QwQ, Ollama reasoning models, early OpenAI o-series) tags.
THINK_EXTRACT_RE = re.compile(
    r'<(?:redacted_thinking|think)>(.*?)(?:</(?:redacted_thinking|think)>|$)',
    re.DOTALL | re.IGNORECASE,
)
THINK_STRIP_RE = re.compile(
    r'<(?:redacted_thinking|think)>.*?(?:</(?:redacted_thinking|think)>|$)',
    re.DOTALL | re.IGNORECASE,
)
INTERNAL_THINK_TAG_RE = re.compile(
    r'^\[(?P<tag>[A-Z0-9_]+)\](?:\s*(?P<payload>.*))?$',
    re.DOTALL,
)
INTERNAL_THINK_LABELS: dict[str, str] = {
    'CHECKPOINT': 'Saving checkpoint…',
    'CHECKPOINT_RESULT': 'Checkpoint…',
    'EXPLORE_TREE_STRUCTURE': 'Exploring code graph…',
    'PREVIEW': 'Preparing preview…',
    'READ_SYMBOL_DEFINITION': 'Reading symbol definitions…',
    'ROLLBACK': 'Reverting…',
    'SCRATCHPAD': 'Updating scratchpad…',
    'VERIFY_FILE_LINES': 'Verifying file lines…',
    'VIEW_AND_REPLACE': 'Preparing edit…',
    'WORKING_MEMORY': 'Updating working memory…',
}
VISIBLE_INTERNAL_BLOCK_TAG_RE = re.compile(
    r'</?(?:WORKING_MEMORY|TASK_TRACKING)>',
    re.IGNORECASE,
)
VISIBLE_INTERNAL_SECTION_RE = re.compile(
    r'^\[(HYPOTHESIS|FINDINGS|DECISIONS|PLAN)\](?:\s*(.*))?$',
    re.IGNORECASE,
)
VISIBLE_SUPPRESSED_LINE_RE = re.compile(
    r'^\[(?:ANALYZE_PROJECT_STRUCTURE|CHECKPOINT|CHECKPOINT_RESULT|'
    r'EXPLORE_TREE_STRUCTURE|PREVIEW|READ_SYMBOL_DEFINITION|'
    r'REVERT_RESULT|ROLLBACK|SCRATCHPAD|SEMANTIC_RECALL_RESULT|'
    r'TASK_TRACKER|VERIFY_FILE_LINES|WORKING_MEMORY)\]\b',
    re.IGNORECASE,
)
THINK_RESULT_JSON_RE = re.compile(
    r'\n?\[(?:CHECKPOINT_RESULT|REVERT_RESULT|ROLLBACK|TASK_TRACKER)\]\s*\{.*',
    re.DOTALL,
)
TOOL_RESULT_TAG_RE = re.compile(r'</?[a-z_][a-z0-9_]*>', re.IGNORECASE)

# -- Command output / failure summarisation ----------------------------------

CMD_SUMMARY_NOISE_PATTERNS: tuple[str, ...] = (
    'a complete log of this run can be found in',
    '[below is the output of the previous command.]',
    '[the command completed with exit code',
    '[app: output truncated',
)
CMD_SUMMARY_PRIORITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r'^\[(shell_mismatch|scaffold_setup_failed|missing_module|missing_tool|'
        r'disk_full|permission_error|oom_killed|segfault|repeated_command_failure)\]',
        re.IGNORECASE,
    ),
    re.compile(r'could not read package\.json', re.IGNORECASE),
    re.compile(r'contains files that could conflict', re.IGNORECASE),
    re.compile(r'operation cancelled', re.IGNORECASE),
    re.compile(r'command not found|not recognized as', re.IGNORECASE),
    re.compile(r'module(?:notfounderror| not found)|importerror', re.IGNORECASE),
    re.compile(r'permission denied', re.IGNORECASE),
    re.compile(r'enoent|eacces|eperm|fatal:|exception|traceback|error', re.IGNORECASE),
)

APPLY_PATCH_TITLE = 'apply patch'
APPLY_PATCH_STATS_RE = re.compile(r'\[APPLY_PATCH_STATS\]\s*\+(\d+)\s*-(\d+)')

# Exact command strings produced by ``backend/execution/browser/grinta_browser.py``
# when it dispatches a ``CmdOutputObservation`` for a browser tool action.
BROWSER_TOOL_COMMANDS = frozenset(
    {
        'browser start',
        'browser close',
        'browser navigate',
        'browser snapshot',
        'browser screenshot',
        'browser click',
        'browser type',
    }
)

# Prefix emitted by ``file_editor._view_directory`` when the editor is pointed
# at a directory rather than a regular file.
DIRECTORY_VIEW_PREFIX = 'Directory contents of '

# -- Error classification ----------------------------------------------------

# Provider / network / quota issues — calm cyan "notice" styling.
RECOVERABLE_NOTICE_FRAGMENTS: tuple[str, ...] = (
    'verification required',
    'blind retries are blocked',
    'fresh grounding action',
    'stuck loop detected',
    'no executable action',
    'no-progress loop',
    'intermediate control tool',
    'timeout',
    'timed out',
    'did not answer before',
    'automatic backoff and retry',
    'retrying without streaming',
    'stream timed out',
    'fallback completion timed out',
    'rate limit',
    'too many requests',
    '429',
    'quota',
    'billing',
    'insufficient_quota',
    'connection',
    'unreachable',
    'connect error',
    'dns',
    'ssl',
    'certificate',
    'econnrefused',
    'econnreset',
    'context length',
    'context window',
    'token limit',
    'max tokens',
    'too large to process',
)

CRITICAL_ERROR_FRAGMENTS: tuple[str, ...] = (
    'syntax validation failed',
    '401',
    'unauthorized',
    'invalid api key',
    'authenticationerror',
    'api key rejected',
    'no api key or model configured',
    'permission denied',
    'access is denied',
    '403',
    'filenotfounderror',
)

DELEGATE_WORKER_STATUS_STYLES: dict[str, str] = {
    'starting': 'cyan',
    'running': 'yellow',
    'done': 'green',
    'failed': 'red',
}
