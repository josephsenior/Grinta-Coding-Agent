---
name: deps
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /deps
  - /dependencies
---

# Dependency management

Use when the user invokes **`/deps`** to add, upgrade, or audit dependencies.
Golden rule: **change one thing, lock it, run tests** before the next change.
Never hand-edit a lockfile.

## Before changing anything

- Identify the package manager from the lockfile present: `uv.lock` / `poetry.lock`
  / `requirements*.txt` (Python), `pnpm-lock.yaml` / `package-lock.json` /
  `yarn.lock` (Node). Use the matching tool, do not mix.
- Note current versions of what you're about to touch so you can roll back.

## Add a dependency

```bash
# Python (uv)
uv add httpx
uv add --dev pytest-mock        # dev-only dependency

# Node
pnpm add zod
npm install --save-dev vitest
```

## Upgrade safely

```bash
# Python (uv): one package, then the lock
uv lock --upgrade-package httpx
uv sync

# Node: one package to its latest allowed by range
pnpm up zod
```

- Upgrade **one package (or one tight group) per commit**.
- Read the changelog for major-version bumps; expect breaking changes.
- Run the test suite after each upgrade, not at the end of a batch.

## Audit for vulnerabilities

```bash
uv pip list --outdated        # or: pip list --outdated
pip-audit                      # Python CVE scan
npm audit                      # Node CVE scan
pnpm audit
```

- Fix **direct** dependencies first; transitive fixes usually follow from a
  direct bump or an override.
- Prefer the minimal version that clears the advisory over jumping to latest.

## Finalize

- Commit the manifest **and** the updated lockfile together.
- If a transitive pin was needed, leave a one-line comment explaining why.
