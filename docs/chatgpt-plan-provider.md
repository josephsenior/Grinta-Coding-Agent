# ChatGPT plan provider

Select `chatgpt-plan/gpt-6.1-sol` to use the public Responses connection.
The existing `codex/` provider remains separately selectable. Normal provider
defaults have not changed.

This is a transport implementation, not a completed sign-in experience. A local
sign-in application must first obtain an OAuth access token authorized for
ChatGPT plan usage and supply it through `GRINTA_CHATGPT_PLAN_ACCESS_TOKEN`.
It must also refresh that token when necessary. Grinta does not currently launch
that browser flow or renew these tokens itself. Do not paste tokens into chat,
configuration files or committed artifacts. Existing Codex credentials are not
assumed to carry the required authorization.

The provider sends full conversation history to `https://api.openai.com/v1`
with storage disabled and streaming enabled. It groups Grinta function tools in
a namespace and converts returned tool calls back to Grinta's normal tool
interface. Grinta continues to execute those tools and control the workflow.
Streaming is buffered until completion before tool calls reach the executor.
Unsupported hosted tools are rejected. Explicit failed, incomplete or interrupted
responses raise an error rather than becoming successful model turns.

SDK retries are disabled. There is no fallback to a paid API key or the Codex
backend. The provider forwards reported token usage; missing usage remains subject
to the existing response converter's behavior and is not evidence of zero usage.

Verification currently consists of offline transport tests, including a simulated
model/tool/result exchange. No live sign-in, model availability or inference has
been verified. This provider is not yet selected by the DeepSWE experiment
protocol; benchmark provisioning and credential delivery need separate updates.

References:

- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview requirements](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
