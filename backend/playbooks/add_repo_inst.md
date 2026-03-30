---
name: add_repo_inst
version: 1.0.0
author: App
agent: Orchestrator
triggers:
  - /add_repo_inst
inputs:
  - name: REPO_FOLDER_NAME
    description: 'Branch for the agent to work on'
---

Please browse the current repository under /workspace/{{ REPO_FOLDER_NAME }}, look at the documentation and relevant code, and understand the purpose of this repository.

Specifically, I want you to create a `.app/playbooks/repo.md` file. This file should contain succinct information that summarizes (1) the purpose of this repository, (2) the general setup of this repo, and (3) a brief description of the structure of this repo.

Here's an example:

```markdown
---
name: repo
type: repo
agent: Orchestrator
---

This repository contains the code for App, an automated AI software engineer. It has a Python backend
(in the `backend` directory) and a React web UI, plus a small `client` package for HTTP/Socket.IO from Python.

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

Web UI:

- Served with the backend (default http://localhost:3000)
- Launch server: `uv run app serve` or `python start_server.py`

Python API client:

- Package `client` — use `AppClient` in tests and scripts
```

Now, please write a similar markdown for the current repository.
Read all the GitHub workflows under .github/ of the repository (if this folder exists) to understand the CI checks (e.g., linter, pre-commit), and include those in the repo.md file.
