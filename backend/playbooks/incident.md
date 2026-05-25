---
name: incident
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /incident
  - /oncall
---

# Incident triage and recovery

Use during live breakage, production regressions, or high-severity user-facing failures.

## 1) Triage fast

- Confirm severity (SEV1/SEV2/SEV3) by user impact and revenue/safety risk.
- Capture first timestamp, affected surface, and suspected release window.
- Start an incident log in the transcript with UTC timestamps.

## 2) Stop the bleed

- Prefer the fastest reversible mitigation: rollback, kill-switch, or traffic throttle.
- If a full rollback is risky, disable only the failing feature path.
- Communicate mitigation ETA before deep root-cause work.

## 3) Narrow blast radius

- Reproduce with smallest failing input.
- Correlate logs, traces, and deploy diffs.
- Identify whether failure is code, config, dependency, or infrastructure.

## 4) Patch safely

- Keep remediation PR minimal and scoped to incident cause.
- Add or update a regression test for the failing path.
- Validate fix in staging/canary before broad rollout.

## 5) Close and learn

- Record root cause, trigger, detection gap, and preventive action.
- Add one permanent guardrail (test, alert, lint, circuit breaker, limit).
- Document follow-up tasks with owners and due dates.

## Incident output format

- Impact
- Mitigation applied
- Root cause
- Fix and verification
- Follow-ups

