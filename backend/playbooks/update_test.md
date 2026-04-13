---
name: update_test
type: task
version: 1.0.0
author: App
agent: Orchestrator
triggers:
  - /update_test
inputs:
  - name: BRANCH_NAME
    description: 'Branch for the agent to work on'
  - name: TEST_COMMAND_TO_RUN
    description: 'The test command you want the agent to work on. For example, `pytest tests/unit/test_bash_parsing.py`'
---

Can you check out branch "{{ BRANCH_NAME }}", and run `{{ TEST_COMMAND_TO_RUN }}`.

Some tests are failing. The current implementation of the code is correct — the tests need to be updated to match it.

Please identify the failing tests, read the current implementation, and update the test file(s) so all tests pass. Do not change the implementation code.
