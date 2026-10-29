# ChatGPT plan provider

Select `chatgpt-plan/gpt-6.1-sol` to use the public Responses connection.
The existing `codex/` provider remains separately selectable. Normal provider
defaults have not changed.

From the repository's Python environment, run:

```sh
python -m backend.inference.clients.chatgpt_plan_auth login
python -m backend.inference.clients.chatgpt_plan_auth status
```

Sign in and approve ChatGPT plan usage in the system browser. Grinta registers
its own client, verifies the callback and signed identity token, and stores the
session in the OS credential store (Windows Credential Manager on Windows).
Refreshes run automatically before expiry, with a process lock to avoid racing
rotating refresh tokens. Codex credentials are not reused. No model request is
made by login or status.

Use `--profile <label>` to register a separate account, and set
`GRINTA_CHATGPT_PLAN_PROFILE` to select that label for inference. The default
profile is `default`. For a separately managed session, the optional environment
override `GRINTA_CHATGPT_PLAN_ACCESS_TOKEN` still bypasses saved-session renewal.
Do not paste tokens into chat, configuration files or committed artifacts.

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

Verification includes offline transport and authorization tests, including a
simulated model/tool/result exchange, callback rejection and token rotation.
Live sign-in and inference need account authorization before they can be verified.
This provider is not yet selected by the DeepSWE experiment
protocol; benchmark provisioning and credential delivery need separate updates.

References:

- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [Preview requirements](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [Sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [Manage plan usage](https://chatgpt.com/settings/usage)
