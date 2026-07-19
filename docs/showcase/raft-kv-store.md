# Raft Key-Value Store

## Task

Build a Raft-backed key-value store with election, replication, failover, partition, persistence, and log-consistency behavior.

## What happened

Grinta created the project and test suite, encountered an asynchronous race around leadership changes, inspected the failing test and network behavior, edited the implementation and validation path, and reran the full suite repeatedly.

## Result

- Tests: **39/39 passed consistently**
- Tracked task groups in the demo: **13**
- Human follow-up messages during recovery: **0**
- Demonstrated behavior: election, replication, failover, partition handling, persistence, and log consistency

## Watch

[Animated recovery sequence](../assets/grinta-demo-preview.webp) · [Full demo](../assets/grinta-demo.mp4)

## Inspect

The recording is the public evidence for this run. A sanitized transcript and diff are not currently published.
