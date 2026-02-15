"""Orchestrate batch D205 fixes using Poetry+ruff and fix_d205_tokens.py.

Usage: python scripts/auto_fix_d205.py

This script will:
- run `poetry run ruff check --select D205` to enumerate D205 findings
- parse file paths, chunk into batches (default 5)
- for each batch: run fix_d205_tokens.py --dry-run, show diffs, apply fixes, then run ruff on the batch
- if new syntax errors or new D2xx issues appear, revert the batch using git
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXER = ROOT / "fix_d205_tokens.py"
BATCH_SIZE = 5


def run_cmd(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )


def enumerate_d205() -> list[Path]:
    print("Enumerating D205 issues with: poetry run ruff check --select D205")
    res = run_cmd(["poetry", "run", "ruff", "check", "--select", "D205"])
    out = res.stdout or ""
    files = []
    for line in out.splitlines():
        if ": D205" in line:
            try:
                path = line.split(":", 1)[0]
                p = (ROOT / path).resolve()
                if p.exists():
                    files.append(p)
            except Exception:
                continue
    seen = set()
    uniq = []
    for p in files:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def chunk(it: list[Path], n: int) -> list[list[Path]]:
    return [it[i : i + n] for i in range(0, len(it), n)]


def run_batch(batch: list[Path]) -> bool:
    print(f"\nProcessing batch ({len(batch)} files):")
    for p in batch:
        print(" -", p.relative_to(ROOT))
    dry_cmd = [sys.executable, str(FIXER), "--dry-run"] + [
        str(p.relative_to(ROOT)) for p in batch
    ]
    print("Running dry-run:", " ".join(dry_cmd))
    dry = run_cmd(dry_cmd)
    print(dry.stdout)
    apply_cmd = [sys.executable, str(FIXER)] + [str(p.relative_to(ROOT)) for p in batch]
    print("Applying fixes:", " ".join(apply_cmd))
    apply_res = run_cmd(apply_cmd)
    print(apply_res.stdout)
    paths = [str(p.relative_to(ROOT)) for p in batch]
    verify_cmd = ["poetry", "run", "ruff", "check"] + paths
    print("Verifying with ruff:", " ".join(verify_cmd))
    verify = run_cmd(verify_cmd)
    print(verify.stdout)
    out = verify.stdout or ""
    if "SyntaxError" in out or "D2" in out:
        print("Problem detected in batch — reverting changes for this batch")
        restore_cmd = ["git", "restore", "--"] + paths
        run_cmd(restore_cmd)
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--batch-size", type=int, default=5, help="number of files per batch"
    )
    parser.add_argument(
        "--yes", action="store_true", help="auto-apply fixes without pause"
    )
    args = parser.parse_args()
    files = enumerate_d205()
    if not files:
        print("No D205 issues found.")
        return
    batches = chunk(files, args.batch_size)
    fixed = 0
    for i, batch in enumerate(batches, start=1):
        print(f"\n=== Batch {i}/{len(batches)} ===")
        ok = run_batch(batch)
        if not ok:
            print(f"Batch {i} failed and was reverted — will skip to next batch.")
            continue
        fixed += len(batch)
    print(
        f"\nDone. Processed {len(files)} files in {len(batches)} batches. Attempted fixes for {fixed} files."
    )


if __name__ == "__main__":
    main()
