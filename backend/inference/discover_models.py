#!/usr/bin/env python3
"""CLI utility for discovering and managing local LLM models.

Usage:
    python -m backend.inference.discover_models          # Discover all local models
    python -m backend.inference.discover_models status   # Check provider status
"""

from __future__ import annotations

import sys

from backend.core.logger import app_logger as logger
from backend.inference.provider_resolver import (
    check_local_providers,
    discover_all_local_models,
)


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def discover_command() -> None:
    """Discover all available local models."""
    print_section("Local Model Discovery")

    print("\nDiscovering local LLM providers...")
    models = discover_all_local_models()

    if not models:
        print("❌ No local providers found.")
        print("\nTo use local models:")
        print("  1. Install Ollama: https://ollama.ai")
        print("  2. Run: ollama pull llama3.2")
        print("  3. Run this command again")
        return

    total_models = sum(len(m) for m in models.values())
    print(f"\n✓ Found {total_models} models across {len(models)} providers:\n")

    for provider, model_list in models.items():
        print(f"📦 {provider.upper()}")
        for model in model_list:
            print(f"   - {model}")

    print("\n💡 Usage examples:")
    if "ollama" in models and models["ollama"]:
        sample_model = models["ollama"][0]
        print(f'   Set llm_model (or LLM config model) to "ollama/{sample_model}"')


def status_command() -> None:
    """Check status of local providers."""
    print_section("Local Provider Status")

    print("\nChecking local LLM providers...\n")
    status = check_local_providers()

    for provider, is_running in status.items():
        status_icon = "✓" if is_running else "✗"
        status_text = "RUNNING" if is_running else "NOT FOUND"
        print(f"{status_icon} {provider.upper():<15} {status_text}")

    if not any(status.values()):
        print("\n💡 No local providers are running.")
        print("\nTo start Ollama:")
        print("  ollama serve")


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        command = "discover"
    else:
        command = sys.argv[1].lower()

    commands = {
        "discover": discover_command,
        "status": status_command,
    }

    if command not in commands:
        print(f"Unknown command: {command}")
        print(f"\nAvailable commands: {', '.join(commands.keys())}")
        return 1

    try:
        commands[command]()
        return 0
    except Exception as e:
        logger.error("Command failed: %s", e, exc_info=True)
        print(f"\n❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
