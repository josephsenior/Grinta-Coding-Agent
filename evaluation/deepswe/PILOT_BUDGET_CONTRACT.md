# Agreed paired-pilot limits

Use GPT-6.1 Sol with medium reasoning through the ChatGPT-plan provider.
Each system receives its own limit of 7,200 seconds and 2,000,000 combined input
and output tokens for each task. The first reached limit stops the run; finishing
early ends it. Model requests, tool execution and candidate validation count.
Provisioning and the initial public baseline are excluded. Retain any token
overshoot from a response already in progress and do not double-count reasoning
tokens that are included in output usage.

Agentless-ML starts with one edit-localization sample and four repair candidates.
First run one paired task and inspect actual usage before the other four.

The canonical machine-readable agreement lives in Agentless-ML:
[agreed_contract.json](https://github.com/josephsenior/Agentless-ML/blob/main/experiments/pilots/deepswe_small_v2/agreed_contract.json).
The prepared-workspace runner enables enforcement with `--pilot-budget`,
`--model chatgpt-plan/gpt-6.1-sol --reasoning-effort medium`. It charges reported
provider input/output usage once, checks tool boundaries and cancels the attempt
at the aggregate deadline. Missing usage stops the attempt. The manifest retains
usage, overshoot and budget-exhaustion status. Normal Grinta has no active budget
scope and retains its existing defaults.

Local checks cover token overshoot, usage accounting and deadline cancellation.
Cancellation is cooperative: cleanup and diagnostic writes may continue beyond
the deadline, and this is not an OS kill switch for detached child processes.
The shared-record live-launch gate remains closed pending integration of the
paired container launcher. No benchmark was run to test these limits.
