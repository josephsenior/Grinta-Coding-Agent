# CLI Theme Contract

This document defines the visual contract for the Grinta CLI UI.  
Goal: keep prompt chrome, transcript cards, and live panels visually coherent across releases.

## Core rules

- Use tokens from `backend/cli/theme.py` and `backend/cli/layout_tokens.py`.
- Do not introduce ad-hoc color hex values in renderer/transcript modules.
- Keep panel titles short, Title Case nouns (`Files`, `Terminal`, `Workers`, `Tool`).
- Keep spacing rhythm consistent via shared helpers (`frame_transcript_body`, panel padding tokens).

## Marker policy

Canonical markers live in `backend/cli/theme.py`:

- `MARK_OK` for success
- `MARK_ERR` for failures
- `MARK_INFO` for neutral info bullets
- `MARK_PROMPT` for the input prompt marker

Do not hardcode equivalent glyphs in feature modules.

## Status semantics

- Success/healthy states use `CLR_STATUS_OK`.
- Warning/review states use `CLR_STATUS_WARN`.
- Error/attention states use `CLR_STATUS_ERR`.
- Prompt badges and Live fake-prompt badges should map state names to the same semantic color.

## Prompt density

Default prompt stats row should prioritize:

1. provider/model
2. tokens
3. cost
4. ledger state
5. call count

Extended diagnostics (for example MCP/skills counts) should live in explicit status surfaces (`/status`), not the default compact prompt line.

## Review checklist for UI changes

- Does this change reuse existing theme/layout tokens?
- Does it preserve status color semantics across prompt + transcript + live panels?
- Does it keep panel title naming consistent?
- Does it avoid adding extra noise to the default prompt?
- Does it keep the same marker set across views?
