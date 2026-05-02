# Dead / orphaned code audit report

Generated from the repository audit workflow (Ruff F401/F841, Vulture, coverage cold spots, script inventory, planner vs dispatch registry review).

## Summary

| Layer | Result |
|-------|--------|
| **Ruff (unused imports/locals)** | Production paths (`backend`, `launch`, `scripts` excluding `backend/tests`): **12 × F401 fixed** via `ruff check --fix`. Full-tree `ruff check` still reports import-sort (**I001**) and other rules unrelated to dead symbols — triage separately. |
| **Vulture** | **`vulture>=2.14`** added to `[dependency-groups].dev`; **`[tool.vulture]`** and **`packaging/vulture_whitelist.py`** added. Ran **`uv run vulture`** → clean after removing unreachable code in `create_pretrained_tokenizer`. |
| **Coverage (unit only)** | **`pytest backend/tests/unit --cov=backend --cov-fail-under=0`** → total **~78%** line coverage. Files at **0%** (see below). **2 failures** in `test_cmd_run.py` (session cwd drift) — appear unrelated to this audit; fix separately. |
| **Scripts** | Top-level `scripts/` utilities inventoried vs docs/CI (see table). |
| **Tool registry** | Orchestrator planner **`build_toolset()`** and **`function_calling._create_tool_dispatch_map()`** align with conditional flags; **`engine/tools/__init__.py`** re-exports are a **subset** — extra modules (`note`, `execute_mcp_tool`, helpers under `structure_editor` / `health_check`, etc.) are **used indirectly**. |

---

## Ruff: production unused imports (baseline)

Fixed locations (auto-fixed):

- `backend/cli/event_renderer.py` — unused theme tokens.
- `backend/cli/transcript.py` — unused layout token imports.
- `backend/execution/action_execution_server_io.py` — unused `json`.
- `backend/execution/base.py` — unused `DebuggerAction` import.
- `backend/inference/llm.py` — unused `json`.

Run periodically:

```bash
uv run ruff check backend launch scripts --select F401,F841 --exclude backend/tests
```

---

## Vulture

- **Command:** `uv run vulture` (reads `[tool.vulture]` in `pyproject.toml`).
- **Paths:** `backend`, `launch`, plus `packaging/vulture_whitelist.py`.
- **Excludes:** `backend/tests`, `backend/evaluation`, `backend/conftest.py`, `**/__pycache__`.
- **`packaging/vulture_whitelist.py`:** Documents expression-only names that match Protocol/unpack false positives (parsed by Vulture; not imported at runtime).

**Real dead code removed:**

- `backend/inference/llm_utils.py` — duplicate unreachable `return name` after `except` in `create_pretrained_tokenizer` (100% confidence).

---

## Coverage “cold spots” (unit suite only)

Modules with **0%** line coverage in `backend/tests/unit` with `--cov=backend`:

| Module | Lines (missed) | Note |
|--------|----------------|------|
| `backend/execution/plugins/agent_skills/database/__init__.py` | 207 / 207 | Optional/heavy database skills; may only run in integration or with DB. |
| `backend/execution/sandbox_helpers/appcontainer_runner.py` | 207 / 207 | Sandbox/container path; not exercised in default unit run. |
| `backend/execution/utils/subprocess_background.py` | 92 / 92 | Background subprocess helper; likely integration/e2e. |

**Interpretation:** 0% here means **uncovered in default unit tests**, not necessarily unreferenced. Cross-check with runtime and integration tests before treating as dead.

---

## `scripts/` and `backend/scripts/` inventory

### Top-level `scripts/`

| File | Referenced in docs / CI / in-file help |
|------|----------------------------------------|
| `check_contributor_bootstrap.sh` | `CONTRIBUTING.md` |
| `smoke_install.sh`, `smoke_install.ps1`, `Dockerfile.smoke` | `CHANGELOG.md` |
| `score_agent_eval_pack.py`, `evals/agent_comparison_pack.json` | `docs/investigations/agent-eval-pack.md` |
| `test_nvidia_kimi.py` | Docstring only (ad-hoc NVIDIA API check) |
| `chess_e2e_verify.py` | Docstring / self-described e2e helper |
| `run_all_in_one.py` | **Not** found in repo-wide doc/CI grep — **orphan risk**; confirm with maintainers. |
| `fix_editor.py` | **Not** found — **orphan risk**. |
| `_splice_observation_handler.py` | **Not** found — **orphan risk** (leading `_` suggests one-off). |
| `measure_tokens.py` | **Replaced** with explicit `SystemExit` and pointer to this report (obsolete `OrchestratorPlanner` + `Settings` API). |

### `backend/scripts/`

Documented in `backend/scripts/README.md` and/or `.github/workflows/py-tests.yml` (e.g. `verify_optional_imports.py`, `check_layer_imports` in pre-commit). Treat any script not listed in those places as **candidates for documentation or removal** after owner review.

---

## Tool registration vs `engine/tools/__init__.py`

- **`__all__` in `backend/engine/tools/__init__.py`** lists the **public factory exports** for tooling/docs.
- **OrchestratorPlanner** (`backend/engine/planner.py`) imports additional factories directly (`note`, `recall`, `execute_mcp_tool`, `blackboard`, `checkpoint`, `browser_native`, `debugger`, `meta_cognition.communicate`, etc.) when config flags allow.
- **`function_calling.py`** dispatch map includes handlers for every tool name exposed through those factories.

**Conclusion:** Do not delete a file under `backend/engine/tools/` solely because it is missing from `__init__.__all__`; trace **`build_toolset`** and **`_create_tool_dispatch_map`** first.

**Support modules** (`atomic_refactor`, `whitespace_handler`, `structure_editor`, `semantic_analyzer`, `health_check`, etc.) are imported from **`structure_editor`**, **`function_calling`**, **`orchestrator`**, or tests — not orphaned.

---

## Intentional legacy / stubs (not bugs)

- `backend/execution/plugins/agent_skills/repo_ops/__init__.py` — vacated stub (compat).
- `backend/orchestration/tool_pipeline.py` — lazy `__getattr__` re-exports.
- `backend/execution/action_execution_server.py` — `__main__` retired; module still used as library.

---

## Safe-delete / follow-up candidates

| Item | Evidence | Risk | Recommendation |
|------|----------|------|----------------|
| Unreachable `return` in `create_pretrained_tokenizer` | Vulture 100% | Low | **Removed** |
| Unused imports (F401 prod) | Ruff | Low | **Fixed** |
| `scripts/measure_tokens.py` | No references; wrong API | Low | **Exit with message** — delete file if undesired |
| `scripts/run_all_in_one.py`, `fix_editor.py`, `_splice_observation_handler.py` | No doc/CI refs | Medium | Confirm with team; archive or document |
| `database` plugin / `appcontainer_runner` / `subprocess_background` | 0% unit cov | High | Likely live in non-unit paths — **do not delete** without proof |

---

## Commands reference

```bash
uv sync --all-groups
uv run ruff check backend launch scripts --select F401,F841 --exclude backend/tests
uv run vulture
uv run pytest backend/tests/unit --cov=backend --cov-fail-under=0 --cov-report=term-missing:skip-covered
```
