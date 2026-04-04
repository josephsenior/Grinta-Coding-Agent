---
name: address_pr_comments
version: 1.0.0
author: App
agent: Orchestrator
triggers:
  - /address_pr_comments
inputs:
  - name: PR_URL
    description: 'URL of the pull request'
  - name: BRANCH_NAME
    description: 'Branch name corresponds to the pull request'
---

First, check out branch `{{ BRANCH_NAME }}` and read the diff against the main branch to understand the purpose of the changes.

This branch corresponds to PR: {{ PR_URL }}

Next, use the GitHub REST API (via `curl` with `$GIT_PROVIDER_TOKEN`) or GitHub MCP tools to fetch all review comments and inline comments on this PR.

For each comment or requested change:
1. Understand what the reviewer is asking for
2. Make the code change, documentation update, or test fix as requested
3. If the request is unclear, implement the most reasonable interpretation

After addressing all comments, push the changes to `{{ BRANCH_NAME }}`. Do not open a new PR or close the existing one.
