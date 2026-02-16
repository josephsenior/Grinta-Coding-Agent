#!/usr/bin/env python3
"""Script to run comprehensive E2E tests for the autonomous system.

Usage:
    python run_autonomous_tests.py --quick          # Run quick tests only
    python run_autonomous_tests.py --full           # Run all tests including Playwright
    python run_autonomous_tests.py --scenario NAME  # Run specific scenario
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def check_requirements():
    """Check if required dependencies are installed."""
    required = ["pytest", "pytest-asyncio"]
    missing = []

    for package in required:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing.append(package)

    if missing:
        print(f"❌ Missing required packages: {', '.join(missing)}")
        print(f"   Install with: pip install {' '.join(missing)}")
        return False

    return True


def run_quick_tests():
    """Run quick E2E tests (no Playwright)."""
    print("=" * 80)
    print("RUNNING QUICK E2E TESTS")
    print("=" * 80)
    print()

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "test_autonomous_real_world.py",
        "-v",
        "--tb=short",
        "-m",
        "e2e and not playwright",
        "--maxfail=3",
    ]

    return subprocess.run(cmd, check=False, cwd=Path(__file__).parent).returncode


def run_specific_test(test_name):
    """Run a specific test scenario."""
    print(f"Running test: {test_name}")
    print("=" * 80)

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "test_autonomous_real_world.py",
        "test_autonomous_chrome_devtools.py",
        "-v",
        "--tb=short",
        "-k",
        test_name,
    ]

    return subprocess.run(cmd, check=False, cwd=Path(__file__).parent).returncode


def run_full_tests():
    """Run all E2E tests including Playwright."""
    print("=" * 80)
    print("RUNNING FULL E2E TEST SUITE")
    print("=" * 80)
    print()

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "test_autonomous_real_world.py",
        "test_autonomous_chrome_devtools.py",
        "-v",
        "--tb=short",
        "-m",
        "e2e",
    ]

    return subprocess.run(cmd, check=False, cwd=Path(__file__).parent).returncode


def list_scenarios():
    """List all available test scenarios."""
    scenarios = [
        "build_simple_todo_app",
        "dangerous_command_blocked",
        "error_recovery_and_retry",
        "circuit_breaker_trips_on_repeated_errors",
        "build_calculator_with_tests",
        "task_validation_prevents_premature_completion",
        "audit_logging_captures_actions",
        "complete_web_app_build",
    ]

    print("Available test scenarios:")
    for i, scenario in enumerate(scenarios, 1):
        print(f"  {i}. {scenario}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Run autonomous system E2E tests")
    parser.add_argument("--quick", action="store_true", help="Run quick tests only")
    parser.add_argument("--full", action="store_true", help="Run all tests")
    parser.add_argument("--scenario", type=str, help="Run specific test scenario")
    parser.add_argument("--list", action="store_true", help="List available scenarios")

    args = parser.parse_args()

    if args.list:
        list_scenarios()
        return 0

    if not check_requirements():
        return 1

    # Check for API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("⚠️  ANTHROPIC_API_KEY not set - some tests may fail")
        print()

    if args.scenario:
        return run_specific_test(args.scenario)
    if args.full:
        return run_full_tests()
    # Default to quick tests
    return run_quick_tests()


if __name__ == "__main__":
    sys.exit(main())
