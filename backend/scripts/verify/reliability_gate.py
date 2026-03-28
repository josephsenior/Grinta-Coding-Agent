"""Run reliability validation gates for hard-cut migration phases.

This script provides one command to execute the release validation bundles used
for migration signoff. It is intentionally cross-platform and model/provider
agnostic: it uses the current Python interpreter and plain pytest invocations.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class GateCommandResult:
    name: str
    command: list[str]
    return_code: int
    duration_seconds: float


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _phase_commands(phase: str, include_integration: bool) -> list[tuple[str, list[str]]]:
    py = [sys.executable, "-m", "pytest", "-q"]

    release1 = [
        (
            "release1_orchestrator_units",
            py + ["backend/tests/unit/engines/orchestrator"],
        ),
        (
            "release1_knowledge_base_units",
              py + ["backend/tests/unit/knowledge"],
        ),
        (
            "release1_step_guard_units",
                py + ["backend/tests/unit/orchestration/services/test_step_guard_service.py"],
        ),
        (
            "release1_error_recovery_memory_units",
            py + [
                "backend/tests/unit/engines/orchestrator/tools/test_error_recovery_memory.py"
            ],
        ),
    ]

    release2 = [
        ("release2_runtime_units", py + ["backend/tests/unit/execution"]),
    ]

    integration = [
        (
            "release2_runtime_integration_filter",
            py + ["backend/tests/integration", "-k", "runtime or prompt or truncation"],
        )
    ]

    if phase == "release1":
        return release1
    if phase == "release2":
        return release2 + (integration if include_integration else [])
    if phase == "full":
        cmds = release1 + release2
        if include_integration:
            cmds += integration
        return cmds
    raise ValueError(f"Unsupported phase: {phase}")


def _run_command(name: str, command: list[str], cwd: Path) -> GateCommandResult:
    start = time.perf_counter()
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    duration = time.perf_counter() - start
    return GateCommandResult(
        name=name,
        command=command,
        return_code=completed.returncode,
        duration_seconds=round(duration, 3),
    )


def _print_summary(results: list[GateCommandResult]) -> None:
    print("\nReliability Gate Summary")
    print("=" * 80)
    for result in results:
        status = "PASS" if result.return_code == 0 else "FAIL"
        cmd = " ".join(result.command)
        print(
            f"[{status}] {result.name} | rc={result.return_code} | "
            f"{result.duration_seconds:.3f}s"
        )
        print(f"       {cmd}")
    total = len(results)
    failed = sum(1 for r in results if r.return_code != 0)
    passed = total - failed
    print("-" * 80)
    print(f"Total: {total}, Passed: {passed}, Failed: {failed}")


def _write_json_report(path: Path, phase: str, results: list[GateCommandResult]) -> None:
    payload = {
        "phase": phase,
        "generated_at_epoch": time.time(),
        "results": [asdict(r) for r in results],
        "passed": all(r.return_code == 0 for r in results),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run hard-cut reliability gates.")
    parser.add_argument(
        "--phase",
        choices=["release1", "release2", "full"],
        default="full",
        help="Validation bundle to run.",
    )
    parser.add_argument(
        "--include-integration",
        action="store_true",
        help="Also run integration filter gate for runtime prompts/truncation.",
    )
    parser.add_argument(
        "--continue-on-fail",
        action="store_true",
        help="Continue running all commands even after a failure.",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=None,
        help="Optional path to write machine-readable report JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing tests.",
    )
    args = parser.parse_args()

    cwd = _repo_root()
    commands = _phase_commands(args.phase, args.include_integration)
    results: list[GateCommandResult] = []

    if args.dry_run:
        print("Reliability gate dry-run")
        for name, command in commands:
            print(f"- {name}: {' '.join(command)}")
        return 0

    for name, command in commands:
        print(f"\n[RUN] {name}")
        result = _run_command(name, command, cwd)
        results.append(result)
        if result.return_code != 0 and not args.continue_on_fail:
            break

    _print_summary(results)

    if args.json_report is not None:
        _write_json_report(args.json_report, args.phase, results)
        print(f"JSON report written to: {args.json_report}")

    return 0 if results and all(r.return_code == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
