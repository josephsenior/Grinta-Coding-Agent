"""Helpers for adapting tool prompts to the current platform.

The unit tests patch `forge.engines.orchestrator.tools.prompt.sys.platform`.
Importing `sys` here exposes the module attribute so that patching succeeds
without raising `AttributeError`.
"""

import re
import sys


def refine_prompt(prompt: str):
    """Refine the prompt based on the current platform.

    On Windows systems, replaces 'bash' with 'powershell' and 'execute_bash' with 'execute_powershell'
    to ensure commands work correctly on the Windows platform.

    Args:
        prompt: The prompt text to refine

    Returns:
        The refined prompt text.

    """
    # Use sys.platform (not platform.system) so tests can monkeypatch
    if sys.platform.lower().startswith("win"):
        result = re.sub(
            r"\bexecute_bash\b", "execute_powershell", prompt, flags=re.IGNORECASE
        )
        return re.sub(
            r"(?<!execute_)(?<!_)\bbash\b", "powershell", result, flags=re.IGNORECASE
        )
    return prompt
