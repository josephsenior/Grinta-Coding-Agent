# Reliability Audit Checklist

Run this checklist before a release candidate or quarterly reliability review.

## Automated suites

1. **Unit + integration reliability tests**
   ```bash
   pytest backend/tests/unit/orchestration/test_pending_action_service.py \
          backend/tests/unit/context/test_prompt_window.py \
          backend/tests/integration/test_hung_action_does_not_wedge_agent.py \
          backend/tests/integration/test_event_stream_persistence_integration.py \
          backend/tests/integration/test_trajectory_regression_harness.py \
          backend/tests/integration/test_reliability_lifecycle_integration.py \
          backend/tests/unit/orchestration/test_health.py
   ```

2. **Full unit suite** (no new failures vs baseline)
   ```bash
   pytest backend/tests/unit
   ```

3. **Stress suite** (nightly / pre-release)
   ```bash
   pytest -m stress backend/tests/stress
   ```

4. **Trajectory regression** (committed fixtures under `backend/tests/fixtures/trajectory_regression/`)
   ```bash
   pytest backend/tests/integration/test_trajectory_regression_harness.py
   ```

## Anti-pattern grep

Run from repository root:

```bash
rg "pending_action\.set\(None\)" backend --glob "!backend/tests/**"
rg "event\.content\s*=" backend/context --glob "!**/*test*"
rg "os\.remove" backend/ledger backend/persistence
rg "_pending_action\s*=\s*None" backend --glob "!backend/tests/**"
```

Expected production call sites should use `clear_for_action`, `clear_primary`, or `clear_all` instead of `set(None)` or `_pending_action = None`.

## Log review

Inspect the last three workspace logs:

```bash
rg "outstanding_count|persistence_health|PERSISTENCE_DEGRADED|DRAIN_STEP_BARRIER_TIMEOUT|lost_events" logs/workspaces/*/sessions/*/session.jsonl
```

Flag any session that ends with `persistence_health=failed` or repeated drain barrier timeouts.

## Health snapshot

For a live session, verify `collect_orchestration_health` returns:

* `severity` not `red` unless the circuit breaker is open
* `persistence_health` == `ok` under normal disk conditions
* no unexpected `retry_pending` or `persistence_failed` warnings

## CI recommendation

| Trigger | Suite |
|---------|-------|
| Pull request | Unit + integration reliability tests (section 1) |
| Nightly | Stress suite + trajectory regression |
