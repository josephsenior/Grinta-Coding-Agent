---
name: update_pr_description
type: task
version: 1.0.0
author: App
agent: Orchestrator
triggers:
  - /update_pr_description
inputs:
  - name: PR_URL
    description: 'URL of the pull request'
    type: string
    validation:
      pattern: '^https://github.com/.+/.+/pull/[0-9]+$'
  - name: BRANCH_NAME
    description: 'Branch name corresponds to the pull request'
    type: string
---

Check out branch `{{ BRANCH_NAME }}` and read the diff against the main branch.

This branch belongs to PR: {{ PR_URL }}

Use the GitHub REST API (via `curl` with `$GIT_PROVIDER_TOKEN`) or GitHub MCP tools to read the existing PR description, then update it to accurately reflect the changes.

A good PR description covers:
- **What** changed and why
- **How** it was implemented (key decisions)
- **Testing** — how to verify it works
- Any **breaking changes** or **migration steps**

Update the description only if it is missing, outdated, or does not reflect the actual changes. Keep it concise and factual.
