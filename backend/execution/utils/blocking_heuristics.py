"""Heuristics for detecting commands that are inherently slow / build-style.

Used by the action-execution layer to default ``CmdRunAction.blocking=True``
when the agent issued a command known to spend long quiet periods (network
fetches, compilation, packaging) but did not explicitly mark it blocking.

The heuristic is intentionally **agnostic** — it operates on the leading
shell tokens only, and never depends on a particular OS or model.
"""

from __future__ import annotations

import re

# Two-token prefixes that should be treated as blocking by default.
# (each entry is a regex matched against the first 1-2 whitespace-delimited tokens)
_BLOCKING_PREFIX_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # JS / TS package managers
        r'^(npm|pnpm|yarn|bun)\s+(i|install|ci|add|update|upgrade|build|run\s+build|test|run\s+test)\b',
        # Python
        r'^(pip|pip3|uv|poetry|pipx)\s+(install|sync|add|update|upgrade|compile|build|wheel)\b',
        r'^python\s+-m\s+(pip|build|venv)\b',
        # Rust
        r'^cargo\s+(build|test|run|check|fetch|update|install|clippy|doc)\b',
        # Go
        r'^go\s+(build|test|mod|install|get|generate|vet)\b',
        # JVM
        r'^(mvn|mvnw|gradle|gradlew|sbt)\b',
        # C/C++/CMake/Make
        r'^(make|gmake|ninja)\b',
        r'^cmake\s+(--build|-G|-S|-B|--install)\b',
        r'^(meson|bazel|buck|buck2)\b',
        # .NET
        r'^dotnet\s+(build|test|publish|restore|run|pack)\b',
        # Containers / images
        r'^docker\s+(build|pull|push|compose\s+(build|up|pull))\b',
        r'^(podman|buildah|nerdctl)\s+(build|pull|push)\b',
        # VCS heavy ops
        r'^git\s+(clone|fetch|pull|submodule\s+(update|init))\b',
        # System package managers
        r'^(apt|apt-get|yum|dnf|pacman|zypper|brew|choco|scoop|winget)\b',
        # Misc compilers / archivers / downloaders
        r'^(rustup|nvm|nvs|pyenv|asdf)\b',
        r'^(curl|wget|aria2c)\b.*\b(--output|-o|-O)\b',  # only large downloads
        r'^(tar|zip|unzip|7z)\b',
    )
)


def is_known_slow_command(command: str) -> bool:
    """Return True if ``command``'s leading tokens match a known-slow pattern.

    The check is deliberately conservative: we only inspect the first words of
    the command string and never the full body, so we will not mis-classify
    inline scripts such as ``echo "npm install"``.
    """
    if not command:
        return False
    head = command.strip().lstrip('(').lstrip()
    # Strip a leading env-var assignment block (e.g. ``DEBUG=1 npm i``).
    while True:
        m = re.match(r'^[A-Za-z_][A-Za-z0-9_]*=\S*\s+', head)
        if not m:
            break
        head = head[m.end():]
    for pat in _BLOCKING_PREFIX_PATTERNS:
        if pat.match(head):
            return True
    return False
