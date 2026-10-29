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
It records an agreement, not completed aggregate enforcement. The historical
DeepSWE protocol and default Grinta behavior have not been changed. Matching
enforcement must be implemented and verified before this pilot starts.
