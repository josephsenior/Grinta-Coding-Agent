# Regression tests

When you fix a bug in production (or in the agent loop), add a **targeted** automated test that fails without the fix and passes with it. Prefer the package that already owns the behavior:

| Area | Typical location |
|------|------------------|
| Session loop, pending actions, retries | `backend/tests/unit/orchestration/` and `backend/orchestration/services/` |
| Shell, files, debugger, ports | `backend/tests/unit/execution/` |
| REPL, slash commands, rendering | `backend/tests/unit/cli/` |
| Config, path validation, logging | `backend/tests/unit/core/` |

**Pattern:** one test (or a small `parametrize` set) that encodes the incident — e.g. a timeout edge case, a state transition, or a bad observation — without duplicating entire orchestration flows. Use existing fixtures and fakes in neighboring tests.

**Not this:** large refactors or “catch-all” tests that only assert imports succeed; those do not lock the specific failure mode.

If a bug is too expensive to run in CI (e.g. requires a full DAP session), add a **unit-level** test around the pure logic you fixed, and document any manual follow-up in the PR.
