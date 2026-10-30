# Agreed paired-pilot limits

As revised by Youssef on 30 October 2026, each system receives 7,200 seconds and
1,000,000 once-only content tokens per task, using GPT-6.1 Sol, medium reasoning,
and the ChatGPT-plan connection. Replayed history does not consume the content
allowance again. Actual cumulative provider input/output usage is still reported
separately and does not enforce this content cap.

The exact normalization, occurrence matching, tokenizer and limitations are in
[the shared contract](https://github.com/josephsenior/Agentless-ML/blob/main/docs/pilot-budget-contract.md).
The machine-readable agreement is
[agreed_contract.json](https://github.com/josephsenior/Agentless-ML/blob/main/experiments/pilots/deepswe_small_v2/agreed_contract.json).
Both systems use byte-identical accounting code. `AttemptBudget.pilot()` enables
the new mode in the shared-container launcher and the opt-in `--pilot-budget`
prepared-workspace path. Normal Grinta defaults and the separate Codex provider
are unchanged.

The counter includes canonical text messages, tool calls/results, instructions
and schemas, using tiktoken 0.14.0 / o200k_base. Every generated reply counts as a
new occurrence. Opaque reasoning is excluded from this content measure while its
actual provider-reported usage remains in `processed_tokens`. This custom content
measure is not provider billing or exact model-specific context-window usage.

Provisioning and the initial public baseline are excluded from time. The first
reached work limit stops the run; cleanup may continue. Missing usage remains a
failure. Subscription limits are independent and no API-key fallback is enabled.
Earlier runs and budget snapshots retain their original cumulative-token meaning.
The revised accounting was checked without live model requests.
