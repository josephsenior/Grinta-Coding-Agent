---
name: add_repo_inst
version: 1.0.0
author: App
agent: Orchestrator
triggers:
  - /add_repo_inst
inputs:
  - name: REPO_FOLDER_NAME
    description: 'Folder name of the repository to document (relative to the working directory)'
---

# Add Repo Instructions

Please browse the current repository under `./{{ REPO_FOLDER_NAME }}` (relative to the working directory), look at the documentation and relevant code, and understand the purpose of this repository.

Specifically, I want you to create a `.grinta/playbooks/repo.md` file. This file should contain succinct information that summarizes (1) the purpose of this repository, (2) the general setup of this repo, and (3) a brief description of the structure of this repo.

Here's an example:

```markdown
---
name: repo
type: repo
agent: Orchestrator
---

This repository contains the code for App, an automated AI software engineer. It has a Python backend
(in the `backend` directory) and ships primarily as a terminal CLI. Optional raw HTTP/OpenAPI tooling may
still exist for compatibility or export workflows, but the supported interactive product surface is the CLI.

## General Setup:

To set up the entire repo, run `make build` (or `uv sync` on Windows).
You don't need to do this unless the user asks you to, or if you're trying to run the entire application.

Before pushing any changes, you should ensure that any lint errors or simple test errors have been fixed.

- Run `pre-commit run --all-files --config ./dev_config/python/.pre-commit-config.yaml`

If the command fails, it may have automatically fixed some issues. You should fix any issues that weren't automatically fixed,
then re-run the command to ensure it passes.

## Repository Structure

Backend:

- Located in the `backend` directory
- Testing:
  - All tests are in `backend/tests/unit/test_*.py`
  - To test new code, run `uv run pytest backend/tests/unit/test_xxx.py` where `xxx` is the appropriate file for the current functionality
  - Write all tests with pytest

CLI:

- Launch the supported interactive product surface with `uv run python -m backend.cli.entry`
- Session commands, init flow, and the REPL live under `backend/cli`

Public server/OpenAPI surface:

- None. The supported product surface is the terminal CLI.
```

Now, please write a similar markdown for the current repository.
Read all the GitHub workflows under .github/ of the repository (if this folder exists) to understand the CI checks (e.g., linter, pre-commit), and include those in the repo.md file.
