"""OpenTelemetry sampling configuration for Forge server."""

import os
import re
from re import Pattern

from backend.core.logger import forge_logger as logger

# Initialize distributed tracing (opt-in — requires `telemetry` extras)
OTEL_ENABLED = os.getenv(
    "TRACING_ENABLED", os.getenv("OTEL_ENABLED", "false")
).lower() in (
    "true",
    "1",
    "yes",
)

try:
    SAMPLE_HTTP = float(
        os.getenv("OTEL_SAMPLE_HTTP", os.getenv("OTEL_SAMPLE_DEFAULT", "0.1"))
    )
except Exception:
    SAMPLE_HTTP = 1.0
SAMPLE_HTTP = max(0.0, min(1.0, SAMPLE_HTTP))

ROUTE_SAMPLE_PATTERNS: list[tuple[str, float, bool]] = []
_route_override_raw = os.getenv("OTEL_SAMPLE_ROUTES", "").strip()
if _route_override_raw:
    for item in _route_override_raw.split(";"):
        item = item.strip()
        if not item or ":" not in item:
            continue
        pattern, rate_str = item.split(":", 1)
        pattern = pattern.strip()
        try:
            rate = float(rate_str.strip())
        except Exception:
            rate = 1.0
        rate = max(0.0, min(1.0, rate))
        is_prefix = pattern.endswith("*")
        if is_prefix:
            pattern = pattern[:-1]
        if not pattern or not pattern.startswith("/"):
            continue
        ROUTE_SAMPLE_PATTERNS.append((pattern, rate, is_prefix))

ROUTE_SAMPLE_REGEX: list[tuple[Pattern, float]] = []
_route_regex_raw = os.getenv("OTEL_SAMPLE_ROUTES_REGEX", "").strip()
if _route_regex_raw:
    for item in _route_regex_raw.split(";"):
        item = item.strip()
        if not item or ":" not in item:
            continue
        pattern, rate_str = item.split(":", 1)
        pattern = pattern.strip()
        try:
            rate = float(rate_str.strip())
        except Exception:
            rate = 1.0
        rate = max(0.0, min(1.0, rate))
        if not pattern:
            continue
        try:
            compiled = re.compile(pattern)
            ROUTE_SAMPLE_REGEX.append((compiled, rate))
        except Exception:
            continue


def get_effective_http_sample(route_path: str) -> float:
    """Return effective sampling probability for a given HTTP route."""
    try:
        # Regex overrides take precedence
        for cregex, sample_rate in ROUTE_SAMPLE_REGEX:
            if cregex.search(route_path):
                return sample_rate
        # Then exact/prefix patterns
        for route_pattern, sample_rate, prefix_match in ROUTE_SAMPLE_PATTERNS:
            if (prefix_match and route_path.startswith(route_pattern)) or (
                not prefix_match and route_path == route_pattern
            ):
                return sample_rate
    except Exception as e:
        logger.debug("Error matching custom sample rate: %s", e)
    return SAMPLE_HTTP
