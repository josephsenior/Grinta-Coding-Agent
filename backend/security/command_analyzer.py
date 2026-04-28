"""Command security analyzer for agentic shell execution.

Classifies shell commands by risk level using pattern-based heuristics.
This is the first line of defence before commands reach the runtime.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.validation.command_classification import argv_tokens

logger = logging.getLogger(__name__)


class RiskCategory(str, Enum):
    """Risk classification for shell commands."""

    NONE = 'none'
    LOW = 'low'
    MEDIUM = 'medium'
    HIGH = 'high'
    CRITICAL = 'critical'


# Numeric ordering used for picking the worst-case risk between raw and
# de-obfuscated forms of the same command.
_RISK_ORDER: dict[RiskCategory, int] = {
    RiskCategory.NONE: 0,
    RiskCategory.LOW: 1,
    RiskCategory.MEDIUM: 2,
    RiskCategory.HIGH: 3,
    RiskCategory.CRITICAL: 4,
}


# Recognised trivial command-substitution wrappers that simply emit their
# argument unchanged. Used by ``_normalize_command`` to defeat shell
# obfuscation like ``$(printf %s rm) -rf /`` or ``$(echo rm) -rf /``.
_TRIVIAL_EMITTERS: frozenset[str] = frozenset({'echo', 'printf'})

# Match a single ``$(...)`` substitution with no nested ``$( ``. We resolve
# innermost-first by repeatedly applying this regex until no further
# substitutions are reduced.
_DOLLAR_PAREN_RE = re.compile(r'\$\(([^()`$]*)\)')
# Match `...` style backtick substitution (single layer, no nesting).
_BACKTICK_RE = re.compile(r'`([^`$]*)`')


def _reduce_trivial_substitution(inner: str) -> str | None:
    """If ``inner`` is a trivial echo/printf, return its literal output.

    Recognises the narrow set of forms an obfuscator typically uses:
        ``echo rm``         -> ``rm``
        ``echo -n rm``      -> ``rm``
        ``printf %s rm``    -> ``rm``
        ``printf '%s' rm``  -> ``rm``
    Anything more complex (pipes, redirections, glob expansion) returns
    None so the substitution is left intact and the original command is
    treated with appropriate suspicion by the caller.
    """
    inner = inner.strip()
    if not inner:
        return ''
    try:
        tokens = shlex.split(inner, posix=True)
    except ValueError:
        return None
    if not tokens:
        return ''
    head = tokens[0].lower()
    if head not in _TRIVIAL_EMITTERS:
        return None
    rest = tokens[1:]
    if head == 'echo':
        # Strip leading -n/-e/-E flags.
        while rest and rest[0] in {'-n', '-e', '-E', '-ne', '-en'}:
            rest = rest[1:]
        return ' '.join(rest)
    if head == 'printf':
        if not rest:
            return ''
        # printf '%s' arg... or printf %s arg...
        fmt = rest[0]
        args = rest[1:]
        if fmt in {'%s', '%s\\n', '%s\\\\n'}:
            return ' '.join(args)
        # Unsupported printf format \u2014 leave intact.
        return None
    return None


def _normalize_command(cmd: str, *, max_iterations: int = 5) -> str:
    """Best-effort de-obfuscation of trivial shell substitutions.

    Iteratively replaces ``$(echo X)``/``$(printf %s X)`` and the
    equivalent backtick form with their literal output. Stops after
    ``max_iterations`` to bound work on adversarial inputs. Anything we
    can't safely reduce is left alone — the caller still classifies the
    raw command, so this is purely additive.
    """
    if '$(' not in cmd and '`' not in cmd:
        return cmd
    out = cmd
    for _ in range(max_iterations):
        prev = out

        def _sub_dollar(match: re.Match[str]) -> str:
            replacement = _reduce_trivial_substitution(match.group(1))
            return replacement if replacement is not None else match.group(0)

        def _sub_backtick(match: re.Match[str]) -> str:
            replacement = _reduce_trivial_substitution(match.group(1))
            return replacement if replacement is not None else match.group(0)

        out = _DOLLAR_PAREN_RE.sub(_sub_dollar, out)
        out = _BACKTICK_RE.sub(_sub_backtick, out)
        if out == prev:
            break
    return out


# Map from RiskCategory to ActionSecurityRisk for convenience.
_RISK_TO_ACTION_LEVEL: dict[str, str] = {
    'none': 'LOW',
    'low': 'LOW',
    'medium': 'MEDIUM',
    'high': 'HIGH',
    'critical': 'HIGH',  # ActionSecurityRisk has no CRITICAL; map to HIGH
}


@dataclass
class CommandAssessment:
    """Structured result from :meth:`CommandAnalyzer.analyze_command`."""

    risk_category: RiskCategory
    reason: str
    recommendations: list[str] = field(default_factory=list)

    # Convenience computed helpers
    is_network_operation: bool = False
    is_encoded: bool = False

    @property
    def risk_level(self) -> Any:
        """Return the corresponding ``ActionSecurityRisk`` enum member."""
        from backend.ledger.action import ActionSecurityRisk

        level_name = _RISK_TO_ACTION_LEVEL.get(self.risk_category.value, 'LOW')
        return ActionSecurityRisk[level_name]


# ---------------------------------------------------------------------------
# Pattern banks – order matters: first match wins within a tier.
# ---------------------------------------------------------------------------

_CRITICAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Destructive filesystem operations
    (
        re.compile(
            r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|--force\s+--recursive|-[a-zA-Z]*f[a-zA-Z]*r)\b',
            re.I,
        ),
        'recursive forced delete',
    ),
    (
        re.compile(r'\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+/\s*$', re.I),
        'recursive delete on root',
    ),
    (re.compile(r'\bmkfs\b', re.I), 'filesystem format'),
    (re.compile(r'\bdd\s+.*\bof=/dev/', re.I), 'raw device write'),
    # Fork bomb — match the canonical ``:(){:|:&};:`` glyph sequence with or
    # without internal whitespace.
    (re.compile(r':\(\)\s*\{[^}]*:\s*\|\s*:\s*&[^}]*\}\s*;\s*:'), 'fork bomb'),
    # Shell redirect into a raw device node — corrupts disks/partitions.
    (re.compile(r'>\s*/dev/(sd[a-z]|nvme|hd[a-z]|vd[a-z]|xvd[a-z])', re.I),
     'redirect into raw block device'),
    # Remote code execution / supply-chain attacks
    (re.compile(r'\bcurl\b.*\|\s*(ba)?sh\b', re.I), 'pipe remote script to shell'),
    (re.compile(r'\bwget\b.*\|\s*(ba)?sh\b', re.I), 'pipe remote download to shell'),
    (re.compile(r'\bcurl\b.*\|\s*python', re.I), 'pipe remote script to python'),
    (re.compile(r'\bwget\b.*\|\s*python', re.I), 'pipe remote download to python'),
    # Encoded payloads / obfuscation
    (re.compile(r'\bbase64\b.*\|\s*(ba)?sh\b', re.I), 'decoded payload piped to shell'),
    (re.compile(r'\bbase64\b.*\|\s*python\b', re.I), 'decoded payload piped to python'),
    # Privilege escalation
    (
        re.compile(r'\bsudo\s+(su|passwd|visudo|chmod\s+[0-7]*7[0-7]*\s+/)\b', re.I),
        'privilege escalation',
    ),
    # Windows equivalents
    (
        re.compile(r'\bRemove-Item\b.*-Recurse.*-Force\b', re.I),
        'recursive forced delete (PowerShell)',
    ),
    (
        re.compile(r'\bRemove-Item\b.*-Force.*-Recurse\b', re.I),
        'recursive forced delete (PowerShell)',
    ),
    (re.compile(r'\bformat\s+[a-zA-Z]:\s*$', re.I), 'drive format (Windows)'),
    (
        re.compile(r'\bdel\b.*(/s|/q).*(/s|/q)', re.I),
        'recursive forced delete (cmd.exe)',
    ),
]

_HIGH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Dangerous but non-destructive
    (re.compile(r'\bsudo\b', re.I), 'sudo usage'),
    (
        re.compile(r'\bdd\s+.*\bif=/dev/(?:zero|random|urandom)\b', re.I),
        'potential device/output flooding via dd',
    ),
    (re.compile(r'\bchmod\s+777\b', re.I), 'world-writable permissions'),
    (re.compile(r'\bchmod\s+[0-7]*7[0-7]*\b', re.I), 'overly permissive chmod'),
    (
        re.compile(r'\bchmod\s+-[a-zA-Z]*[rR][a-zA-Z]*\b', re.I),
        'recursive chmod',
    ),
    (
        re.compile(r'\bchmod\s+(\+s|[ugoa]+\+s)\b', re.I),
        'setuid/setgid permission change',
    ),
    (re.compile(r'\bchown\s+-R\b', re.I), 'recursive ownership change'),
    (re.compile(r'\brm\s+-[a-zA-Z]*r\b', re.I), 'recursive delete'),
    (re.compile(r'\brm\s+-[a-zA-Z]*f\b', re.I), 'forced delete'),
    # Credential / env exfiltration
    (re.compile(r'\benv\b|\bprintenv\b', re.I), 'environment variable dump'),
    (
        re.compile(
            r'\bcat\s+.*(/etc/passwd|/etc/shadow|\.ssh/|\.env|\.aws/credentials)', re.I
        ),
        'credential file read',
    ),
    (
        re.compile(r'\bexport\b.*(_KEY|_SECRET|_TOKEN|PASSWORD)\b', re.I),
        'secret export',
    ),
    # Network exfiltration
    (re.compile(r'\bnc\s+-l\b|\bncat\b|\bnetcat\b', re.I), 'netcat listener'),
    (re.compile(r'\bcurl\b.*-d\s+@', re.I), 'curl data exfiltration'),
    (re.compile(r'\bscp\b|\brsync\b.*@', re.I), 'remote file transfer'),
    # System modification
    (re.compile(r'\bsystemctl\s+(stop|disable|mask)\b', re.I), 'service disruption'),
    (
        re.compile(r'\bsystemctl\s+(start|restart|reload|enable|reboot|poweroff|halt)\b', re.I),
        'systemctl service control',
    ),
    (
        re.compile(r'(?:^|[\s;&|`])(reboot|shutdown|halt|poweroff)\b', re.I),
        'host power-state change',
    ),
    (
        re.compile(r'\binit\s+[06]\b', re.I),
        'host runlevel change',
    ),
    (re.compile(r'\biptables\b|\bnft\b', re.I), 'firewall modification'),
    (re.compile(r'\bcrontab\s+-[er]\b', re.I), 'cron modification'),
    # Windows
    (re.compile(r'\bRemove-Item\b.*-Recurse\b', re.I), 'recursive delete (PowerShell)'),
    (re.compile(r'\bRemove-Item\b.*-Force\b', re.I), 'forced delete (PowerShell)'),
    (
        re.compile(r'\bSet-ExecutionPolicy\s+Unrestricted\b', re.I),
        'execution policy bypass',
    ),
    (re.compile(r'\bReg\s+(Add|Delete)\b', re.I), 'registry modification'),
    (re.compile(r'\bdel\b.*(/s|/q)', re.I), 'file deletion (cmd.exe)'),
]

_MEDIUM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\bcurl\b|\bwget\b', re.I), 'network download'),
    (re.compile(r'\beval\b', re.I), 'eval execution'),
    # Package installation (supply-chain + network)
    (re.compile(r'\bpython\s+-m\s+pip\s+install\b', re.I), 'python -m pip install'),
    (re.compile(r'\bpip(?:3)?\s+install\b', re.I), 'pip install'),
    (re.compile(r'\bnpm\s+install\b', re.I), 'npm install'),
    (re.compile(r'\bgit\s+push\b', re.I), 'git push'),
    (re.compile(r'\bgit\s+clone\b', re.I), 'git clone'),
    (re.compile(r'\bkill\b|\bkillall\b|\bpkill\b', re.I), 'process termination'),
    (re.compile(r'\bmv\s+.*\s+/', re.I), 'move to system directory'),
    (re.compile(r'\bchmod\b', re.I), 'permission change'),
    (
        re.compile(r'\bInstall-Module\b|\bInstall-Package\b', re.I),
        'PowerShell package install',
    ),
]


class CommandAnalyzer:
    """Classify shell commands by security risk.

    Uses layered pattern matching: CRITICAL → HIGH → MEDIUM → LOW.
    First match at each tier wins.  Unknown commands default to LOW.

    Config keys (all optional):
        blocked_commands: list[str] — literal command prefixes to block.
        allowed_commands: list[str] — literal command prefixes always LOW.
        extra_critical_patterns: list[str] — additional regex strings for CRITICAL.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config: dict[str, Any] = config or {}
        self._blocked: list[str] = self.config.get(
            'blocked_commands'
        ) or self.config.get('blocked_prefixes', [])
        self._allowed: list[str] = self.config.get(
            'allowed_commands'
        ) or self.config.get('allowed_exceptions', [])

        # Regex-based policy rules (used by integration tests)
        self._blocked_regex: list[tuple[re.Pattern[str], str]] = []
        for pat_str in self.config.get('blocked_patterns', []) or []:
            try:
                self._blocked_regex.append((re.compile(pat_str, re.I), pat_str))
            except re.error as exc:
                logger.warning('Invalid blocked_pattern %r: %s', pat_str, exc)

        # Compile any user-supplied extra patterns
        self._extra_critical: list[tuple[re.Pattern[str], str]] = []
        for pat_str in self.config.get('extra_critical_patterns', []):
            try:
                self._extra_critical.append(
                    (re.compile(pat_str, re.I), f'custom rule: {pat_str[:40]}')
                )
            except re.error as exc:
                logger.warning('Invalid extra_critical_pattern %r: %s', pat_str, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, command: str) -> tuple[RiskCategory, str, list[str]]:
        """Classify *command* and return ``(risk, reason, recommendations)``.

        Returns:
            A 3-tuple of ``(RiskCategory, human-readable reason, list of
            recommendation strings)``.
        """
        if not command or not command.strip():
            return RiskCategory.NONE, 'empty command', []

        cmd = command.strip()

        # Obfuscation pre-pass: collapse trivial command substitutions like
        # ``$(printf %s rm) -rf /`` or ``$(echo rm) -rf /`` to their literal
        # form so downstream regex patterns can match. We classify both the
        # original and the normalized form and keep whichever risk is higher.
        normalized = _normalize_command(cmd)
        if normalized != cmd:
            norm_risk, norm_reason, norm_recs = self._classify_unnormalized(
                normalized
            )
            raw_risk, raw_reason, raw_recs = self._classify_unnormalized(cmd)
            if _RISK_ORDER.get(norm_risk, 0) > _RISK_ORDER.get(raw_risk, 0):
                return (
                    norm_risk,
                    f'{norm_reason} (after de-obfuscating substitution: {normalized!r})',
                    norm_recs
                    + ['Reject commands that hide intent behind shell substitution.'],
                )
            return raw_risk, raw_reason, raw_recs

        return self._classify_unnormalized(cmd)

    def _classify_unnormalized(
        self, cmd: str
    ) -> tuple[RiskCategory, str, list[str]]:
        """Pattern classification on a (possibly already normalized) command."""
        blocked = _check_blocklist_allowlist(
            cmd, self._blocked_regex, self._blocked, self._allowed
        )
        if blocked is not None:
            return blocked

        has_chaining = bool(re.search(r'(?:;|&&|\|\||\||&|`|\$\()', cmd))
        risk, reason, recs = self._match_tier(
            cmd, self._extra_critical + _CRITICAL_PATTERNS, RiskCategory.CRITICAL
        )
        if risk == RiskCategory.CRITICAL:
            return risk, reason, recs

        risk, reason, recs = self._match_tier(cmd, _HIGH_PATTERNS, RiskCategory.HIGH)
        if risk == RiskCategory.HIGH:
            return _escalate_if_chaining(
                risk,
                reason,
                recs,
                has_chaining,
                RiskCategory.CRITICAL,
                'Command chaining with high-risk operations is critical.',
            )

        risk, reason, recs = self._match_tier(
            cmd, _MEDIUM_PATTERNS, RiskCategory.MEDIUM
        )
        if risk == RiskCategory.MEDIUM:
            return _escalate_if_chaining(
                risk,
                reason,
                recs,
                has_chaining,
                RiskCategory.HIGH,
                'Review chained commands for unintended side-effects.',
            )

        return RiskCategory.LOW, 'no risk: no known risk patterns', []

    def analyze_command(self, command: str) -> CommandAssessment:
        """Higher-level wrapper returning a :class:`CommandAssessment`.

        Delegates to :meth:`analyze` and enriches the result with boolean
        convenience flags expected by integration tests. Risk policy remains
        regex-oriented here; tokenization is shared with validation so both
        layers reason over the same argv splitting rules.
        """
        risk, reason, recs = self.analyze(command)
        cmd = (command or '').strip()
        tokens = [t.lower() for t in argv_tokens(cmd)]
        is_network = any(
            tok in {'curl', 'wget', 'nc', 'ncat', 'netcat', 'scp', 'rsync'}
            for tok in tokens
        )
        is_encoded = any(tok in {'base64', 'xxd'} for tok in tokens) or bool(
            re.search(r'\b\\x[0-9a-f]', cmd, re.I)
        )

        risk, reason = _escalate_encoded_risk(risk, reason, is_encoded)
        reason = _enrich_reason_with_keywords(risk, reason, is_network, is_encoded)

        return CommandAssessment(
            risk_category=risk,
            reason=reason,
            recommendations=recs,
            is_network_operation=is_network,
            is_encoded=is_encoded,
        )

    @staticmethod
    def _match_tier(
        cmd: str,
        patterns: list[tuple[re.Pattern[str], str]],
        tier: RiskCategory,
    ) -> tuple[RiskCategory, str, list[str]]:
        """Return *tier* result on first pattern match, else NONE."""
        for pattern, description in patterns:
            if pattern.search(cmd):
                recs = _RECOMMENDATIONS.get(tier, [])
                return tier, description, recs
        return RiskCategory.NONE, '', []


def _check_blocklist_allowlist(
    cmd: str,
    blocked_regex: list,
    blocked: list,
    allowed: list,
) -> tuple[RiskCategory, str, list[str]] | None:
    """Return (risk, reason, recs) if blocked/allowed, else None."""
    for cregex, raw in blocked_regex:
        if cregex.search(cmd):
            return (
                RiskCategory.CRITICAL,
                f'Custom blocked pattern: {raw}',
                ['This command matched a custom blocked pattern.'],
            )
    for prefix in blocked:
        if cmd.startswith(prefix):
            return (
                RiskCategory.CRITICAL,
                f'blocked by policy: {prefix}',
                ['This command is explicitly blocked by security policy.'],
            )
    for prefix in allowed:
        if cmd.startswith(prefix):
            return RiskCategory.LOW, f'Whitelisted: {prefix}', []
    return None


def _escalate_if_chaining(
    risk: RiskCategory,
    reason: str,
    recs: list[str],
    has_chaining: bool,
    escalated_tier: RiskCategory,
    extra_rec: str,
) -> tuple[RiskCategory, str, list[str]]:
    """Escalate risk if chaining detected, else return unchanged."""
    if not has_chaining:
        return risk, reason, recs
    return (
        escalated_tier,
        f'{reason} (escalated: command chaining detected)',
        recs + [extra_rec],
    )


def _escalate_encoded_risk(
    risk: RiskCategory, reason: str, is_encoded: bool
) -> tuple[RiskCategory, str]:
    """Escalate risk to HIGH if encoded and not already CRITICAL/HIGH."""
    if not is_encoded or risk in (RiskCategory.CRITICAL, RiskCategory.HIGH):
        return risk, reason
    return RiskCategory.HIGH, reason or 'encoded payload'


def _enrich_reason_with_keywords(
    risk: RiskCategory, reason: str, is_network: bool, is_encoded: bool
) -> str:
    """Prepend integration-test keywords. Simplified with rule list."""
    rules: list[tuple[bool, str]] = [
        (
            risk == RiskCategory.CRITICAL
            and not reason.startswith('Custom blocked pattern'),
            'critical',
        ),
        (risk == RiskCategory.HIGH, 'high-risk'),
        (
            risk in (RiskCategory.LOW, RiskCategory.NONE)
            and 'no risk' not in reason.lower(),
            'no risk',
        ),
        (is_network and 'network' not in reason.lower(), 'network'),
        (is_encoded and 'obfuscated' not in reason.lower(), 'obfuscated'),
    ]
    parts = [kw for cond, kw in rules if cond]
    if not parts:
        return reason
    return f'{", ".join(parts)}: {reason}' if reason else ', '.join(parts)


# ---------------------------------------------------------------------------
# Canned recommendation strings per tier
# ---------------------------------------------------------------------------
_RECOMMENDATIONS: dict[RiskCategory, list[str]] = {
    RiskCategory.CRITICAL: [
        'This command is extremely dangerous. Do NOT execute without explicit user approval.',
        'Consider running in an isolated runtime environment.',
    ],
    RiskCategory.HIGH: [
        'Review this command carefully before execution.',
        'Prefer running inside a container or restricted runtime.',
    ],
    RiskCategory.MEDIUM: [
        'Monitor the output of this command for unexpected behaviour.',
    ],
}

# Reflection middleware historically blocked these before execution. Kept so
# behavior stays at least as strict as the old inline regex list while CRITICAL
# covers most overlap (mkfs, many rm/dd variants, etc.).
_REFLECTION_LEGACY_BLOCK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r'\brm\s+-rf\s+/', re.I), 'recursive forced delete toward root path'),
    (re.compile(r'\bdd\s+if=', re.I), 'dd with explicit if='),
    (re.compile(r'\bmkfs\s+', re.I), 'filesystem format (mkfs)'),
    (re.compile(r'\bformat\s+', re.I), 'format-style disk operation'),
    (re.compile(r'>\s+/dev/', re.I), 'shell redirect into /dev'),
]


def reflection_precheck_should_block(
    command: str, *, analyzer: CommandAnalyzer | None = None
) -> tuple[bool, str]:
    """Return whether reflection middleware should block *command* before runtime.

    Combines :class:`CommandAnalyzer` **CRITICAL** tier with a small legacy
    pattern set that matched the pre-dedupe reflection list, so we do not
    regress on edge cases that were HIGH/MEDIUM in the analyzer but still
    blocked in reflection (e.g. ``dd if=file`` without ``of=/dev/``).

    Returns:
        ``(True, reason)`` to block, else ``(False, "")``.
    """
    cmd = (command or '').strip()
    if not cmd:
        return False, ''

    inst = analyzer if analyzer is not None else CommandAnalyzer()
    risk, reason, _ = inst.analyze(cmd)
    if risk == RiskCategory.CRITICAL:
        return True, reason

    for pattern, description in _REFLECTION_LEGACY_BLOCK_PATTERNS:
        if pattern.search(cmd):
            return True, description

    return False, ''


__all__ = [
    'CommandAnalyzer',
    'CommandAssessment',
    'RiskCategory',
    'reflection_precheck_should_block',
]
