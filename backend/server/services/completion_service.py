"""Service for code completion via LLM with circuit breaker, budget, retry, and safety.

Extracted from backend.server.routes.conversation to keep route handlers thin.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.controller.agent_circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
)
from backend.controller.error_recovery import ErrorRecoveryStrategy, ErrorType
from backend.core.cache.async_smart_cache import AsyncSmartCache
from backend.core.constants import COMPLETION_TIMEOUT
from backend.core.logger import FORGE_logger as logger
from backend.events.action import ActionSecurityRisk
from backend.llm.cost_tracker import record_llm_cost_from_response

if TYPE_CHECKING:
    from backend.core.config.llm_config import LLMConfig


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompletionRequest:
    """Immutable value object for a code completion request."""

    file_path: str
    file_content: str
    language: str
    position: dict[str, int]
    prefix: str
    suffix: str


@dataclass(frozen=True)
class CompletionResult:
    """Immutable value object for a code completion result."""

    completion: str
    stop_reason: str | None = None
    security_risk: str | None = None
    warning: str | None = None
    error: str | None = None
    error_type: str | None = None
    status_code: int = 200


# ---------------------------------------------------------------------------
# Circuit breaker & tracking state (per-conversation)
# ---------------------------------------------------------------------------

_circuit_breakers: dict[str, CircuitBreaker] = {}
_error_tracking: dict[str, dict[str, Any]] = defaultdict(
    lambda: {
        "consecutive_errors": 0,
        "recent_errors": [],
        "recent_success": [],
        "last_error_time": None,
    }
)
_budgets: dict[str, dict[str, Any]] = defaultdict(
    lambda: {
        "total_cost": 0.0,
        "request_count": 0,
        "max_cost_per_request": 0.01,
        "max_total_cost": 1.0,
        "budget_exceeded": False,
    }
)
_retry_tracking: dict[str, dict[str, Any]] = defaultdict(
    lambda: {
        "retry_count": 0,
        "max_retries": 3,
        "last_retry_time": None,
        "retry_backoff": 1.0,
    }
)
_config_cache: AsyncSmartCache | None = None

# Suspicious patterns indicating hallucination
_SUSPICIOUS_PATTERNS = [
    "I have created",
    "I have written",
    "I have edited",
    "I've created",
    "I've written",
    "I've edited",
    "The file has been",
    "File created successfully",
]

# Security patterns
_HIGH_RISK_PATTERNS = [
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__\s*\(",
    r"compile\s*\(",
    r"subprocess\s*\.(call|run|Popen)",
    r"os\s*\.(system|popen|exec)",
    r"shell\s*=\s*true",
    r"rm\s+-rf",
    r"del\s+/",
    r"format\s*\(.*%",
    r"\.format\s*\(.*\{.*\}",
]

_MEDIUM_RISK_PATTERNS = [
    r"open\s*\(",
    r"file\s*\(",
    r"pickle\s*\.(load|dumps)",
    r"yaml\s*\.(load|safe_load)",
    r"json\s*\.loads",
    r"requests\s*\.(get|post)",
    r"urllib\s*\.(urlopen|request)",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_config_cache() -> AsyncSmartCache:
    global _config_cache
    if _config_cache is None:
        _config_cache = AsyncSmartCache()
    return _config_cache


def _get_circuit_breaker(conversation_id: str) -> CircuitBreaker:
    if conversation_id not in _circuit_breakers:
        cfg = CircuitBreakerConfig(
            enabled=True,
            max_consecutive_errors=5,
            max_high_risk_actions=10,
            max_stuck_detections=3,
        )
        _circuit_breakers[conversation_id] = CircuitBreaker(cfg)
    return _circuit_breakers[conversation_id]


def check_circuit_breaker(conversation_id: str) -> tuple[bool, str | None]:
    """Return ``(should_block, reason)``."""
    tracking = _error_tracking[conversation_id]
    if tracking["consecutive_errors"] >= 5:
        return (
            True,
            f"Too many consecutive errors ({tracking['consecutive_errors']}). Circuit breaker tripped.",
        )
    recent = tracking["recent_success"][-10:]
    if len(recent) >= 10:
        error_count = sum(1 for s in recent if not s)
        if error_count / len(recent) >= 0.5:
            return (
                True,
                f"Error rate too high ({error_count / len(recent):.0%}). Circuit breaker tripped.",
            )
    return False, None


def record_error(conversation_id: str, exc: Exception) -> None:
    tracking = _error_tracking[conversation_id]
    tracking["consecutive_errors"] += 1
    tracking["recent_errors"].append(str(exc))
    tracking["recent_success"].append(False)
    tracking["last_error_time"] = time.time()
    tracking["recent_success"] = tracking["recent_success"][-20:]
    tracking["recent_errors"] = tracking["recent_errors"][-20:]


def record_success(conversation_id: str) -> None:
    tracking = _error_tracking[conversation_id]
    tracking["consecutive_errors"] = 0
    tracking["recent_success"].append(True)
    tracking["recent_success"] = tracking["recent_success"][-20:]


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    from backend.llm.cost_tracker import get_completion_cost

    return get_completion_cost(model, prompt_tokens, completion_tokens)


def track_cost(
    model: str, prompt_tokens: int, completion_tokens: int, user_key: str
) -> float:
    cost = estimate_cost(model, prompt_tokens, completion_tokens)
    try:
        mock_response = {
            "model": model,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        record_llm_cost_from_response(user_key, mock_response, model)
    except Exception as e:
        logger.debug("Failed to record cost via cost tracker: %s", e)
    return cost


def analyze_security(completion: str) -> tuple[ActionSecurityRisk, str | None]:
    """Return ``(risk_level, warning_message)``."""
    lower = completion.lower()
    for pattern in _HIGH_RISK_PATTERNS:
        if re.search(pattern, lower):
            return ActionSecurityRisk.HIGH, f"High-risk pattern detected: {pattern}"
    for pattern in _MEDIUM_RISK_PATTERNS:
        if re.search(pattern, lower):
            return ActionSecurityRisk.MEDIUM, f"Medium-risk pattern detected: {pattern}"
    return ActionSecurityRisk.LOW, None


def sanitize_completion(raw: str) -> str:
    """Strip markdown fences and suspicious hallucination content."""
    text = raw.strip()
    # Remove markdown code blocks
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) > 1:
            text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3].strip()
    # Truncate if too long
    if len(text) > 1000:
        logger.warning("Completion too long (%d chars), truncating", len(text))
        text = text[:1000]
    # Remove suspicious hallucination patterns
    lower = text.lower()
    for pattern in _SUSPICIOUS_PATTERNS:
        idx = lower.find(pattern.lower())
        if idx >= 0:
            logger.warning("Suspicious pattern detected in completion: %s", pattern)
            text = text[:idx].strip() if idx > 0 else ""
            lower = text.lower()
    return text


def format_error_message(exc: Exception, error_type: ErrorType) -> str:
    """Format user-friendly error message based on classified error type."""
    error_str = str(exc)
    messages = {
        ErrorType.NETWORK_ERROR: (
            "Unable to connect to the AI service. Check connectivity or try again."
        ),
        ErrorType.TIMEOUT_ERROR: (
            "Code completion request timed out. Try a simpler request or wait a moment."
        ),
        ErrorType.PERMISSION_ERROR: (
            "Insufficient permissions. Check your API key and account access."
        ),
        ErrorType.MODULE_NOT_FOUND: (f"Missing module: {error_str[:200]}"),
    }
    base = messages.get(error_type, f"Error: {error_str[:200]}")
    return f"{base}\n\nError type: {error_type.value}"


def _build_prompt(req: CompletionRequest) -> list[dict[str, str]]:
    """Build LLM messages for code completion."""
    prompt = (
        f"You are a code completion assistant. Complete the code at the cursor position.\n\n"
        f"File: {req.file_path}\nLanguage: {req.language}\n\n"
        f"Code before cursor:\n```{req.language}\n{req.prefix}\n```\n\n"
        f"Code after cursor:\n```{req.language}\n{req.suffix}\n```\n\n"
        f"IMPORTANT:\n"
        f"- Provide ONLY the completion text at the cursor position\n"
        f"- Do NOT repeat the prefix or include the suffix\n"
        f"- Do NOT claim to have created, edited, or modified files\n"
        f"- Return only the code that completes the current statement\n"
        f"- Be concise and accurate"
    )
    return [
        {
            "role": "system",
            "content": "You are a helpful code completion assistant. Provide concise, accurate code completions. Never claim to have performed file operations.",
        },
        {"role": "user", "content": prompt},
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_code_completion(
    *,
    req: CompletionRequest,
    conversation_sid: str,
    user_id: str | None,
    llm_config: LLMConfig,
    manager: Any,
    anti_hallucination: Any,
) -> CompletionResult:
    """Execute a code completion request with full resilience stack.

    Parameters
    ----------
    req:
        The completion request value object.
    conversation_sid:
        Conversation session ID (used for circuit breaker / budget scoping).
    user_id:
        Authenticated user ID.
    llm_config:
        LLM configuration for the request.
    manager:
        ConversationManager instance.
    anti_hallucination:
        FileVerificationGuard instance.

    Returns:
    -------
    CompletionResult
        Always returns a result — errors are encoded in the result rather than raised.
    """
    # 1. Circuit breaker check
    should_block, block_reason = check_circuit_breaker(conversation_sid)
    if should_block:
        logger.warning(
            "Completion blocked by circuit breaker for %s: %s",
            conversation_sid,
            block_reason,
        )
        return CompletionResult(
            completion="",
            stop_reason="circuit_breaker_tripped",
            error=block_reason
            or "Service temporarily unavailable due to high error rate.",
            status_code=503,
        )

    # 2. Build messages
    messages = _build_prompt(req)
    budget = _budgets[conversation_sid]
    retry = _retry_tracking[conversation_sid]
    completion_text: str | None = None
    last_error: Exception | None = None

    # 3. Retry loop
    for attempt in range(retry["max_retries"] + 1):
        try:
            # Budget check
            prompt_tokens_est = len(str(messages)) // 4
            estimated_cost = estimate_cost(llm_config.model, prompt_tokens_est, 100)
            if budget["total_cost"] + estimated_cost > budget["max_total_cost"]:
                budget["budget_exceeded"] = True
                return CompletionResult(
                    completion="",
                    stop_reason="budget_exceeded",
                    error=f"Budget exceeded. Current: ${budget['total_cost']:.4f}, Max: ${budget['max_total_cost']:.2f}",
                    status_code=402,
                )

            # LLM call with timeout
            completion_text = await asyncio.wait_for(
                manager.request_llm_completion(
                    sid=conversation_sid,
                    service_id="code_completion",
                    llm_config=llm_config,
                    messages=messages,
                ),
                timeout=COMPLETION_TIMEOUT,
            )

            # Track cost on success
            actual_prompt = len(str(messages)) // 4
            actual_completion = len(completion_text or "") // 4
            actual_cost = track_cost(
                llm_config.model,
                actual_prompt,
                actual_completion,
                f"user:{user_id or 'anonymous'}:conversation:{conversation_sid}",
            )
            budget["total_cost"] += actual_cost
            budget["request_count"] += 1
            retry["retry_count"] = 0
            retry["retry_backoff"] = 1.0
            break

        except TimeoutError as e:
            last_error = e
            if attempt < retry["max_retries"]:
                wait = retry["retry_backoff"] * (2**attempt)
                logger.warning(
                    "Completion timeout (attempt %d/%d), retry in %.1fs",
                    attempt + 1,
                    retry["max_retries"] + 1,
                    wait,
                )
                await asyncio.sleep(wait)
                retry["retry_backoff"] = wait
            else:
                record_error(conversation_sid, e)
                return CompletionResult(
                    completion="",
                    stop_reason="timeout",
                    error=f"Timed out after {retry['max_retries'] + 1} attempts.",
                    status_code=504,
                )
        except Exception as e:
            last_error = e
            error_type = ErrorRecoveryStrategy.classify_error(e)
            is_retryable = error_type in (
                ErrorType.NETWORK_ERROR,
                ErrorType.TIMEOUT_ERROR,
                ErrorType.RUNTIME_CRASH,
            )
            if is_retryable and attempt < retry["max_retries"]:
                wait = retry["retry_backoff"] * (2**attempt)
                logger.warning(
                    "Completion error (%s, attempt %d/%d), retry in %.1fs",
                    error_type.value,
                    attempt + 1,
                    retry["max_retries"] + 1,
                    wait,
                )
                await asyncio.sleep(wait)
                retry["retry_backoff"] = wait
            else:
                raise

    if completion_text is None:
        if last_error:
            raise last_error
        raise RuntimeError("Code completion failed: unknown error")

    # 4. Sanitize
    completion = sanitize_completion(completion_text)

    # 5. Security validation
    risk, warning = analyze_security(completion)
    if risk == ActionSecurityRisk.HIGH:
        record_error(conversation_sid, Exception(f"High security risk: {warning}"))
        return CompletionResult(
            completion="",
            stop_reason="security_risk_high",
            warning=f"Blocked: {warning}",
        )

    # 6. Anti-hallucination
    is_valid, err_msg = anti_hallucination.validate_response(
        response_text=completion, actions=[]
    )
    if not is_valid:
        record_error(conversation_sid, Exception(f"Hallucination: {err_msg}"))
        return CompletionResult(
            completion="",
            stop_reason="hallucination_detected",
            warning="Validation failed. Please try again.",
        )

    # 7. Success
    record_success(conversation_sid)
    logger.info(
        "Completion OK for %s (lang=%s, len=%d, risk=%s)",
        req.file_path,
        req.language,
        len(completion),
        risk.value,
    )
    return CompletionResult(
        completion=completion,
        stop_reason="stop" if completion else "empty",
        security_risk=risk.name.lower() if risk != ActionSecurityRisk.LOW else None,
    )
