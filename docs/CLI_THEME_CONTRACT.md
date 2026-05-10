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

## Available theme presets

| Preset                        | Description                                                                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default` / `dark`            | Navy-dark with cyan accents (original)                                                                                                            |
| `light`                       | Light background variant                                                                                                                          |
| `high-contrast`               | Accessibility-first: bold ANSI colors, no hex                                                                                                     |
| `ocean`                       | Blue-water palette                                                                                                                                |
| `mono`                        | Monochrome with dim/bold only                                                                                                                     |
| `deep-system-instrumentation` | NASA mission-control aesthetic: `#0a0e14` navy bg, `#5fb3b3` teal accents, `#99c794` emerald, `#ec5f67` coral. Designed for long coding sessions. |

### Theme activation

- CLI flag: `grinta --theme deep-system-instrumentation`
- Environment: `GRINTA_THEME=deep-system-instrumentation`

## "Deep System Instrumentation" palette reference

| Element        | Hex       | Description                             |
| -------------- | --------- | --------------------------------------- |
| Background     | `#0a0e14` | Deep navy ink                           |
| Surface        | `#0f151c` | Card/panel surfaces                     |
| Borders        | `#1b2b34` | Subtle structural dividers              |
| Primary accent | `#5fb3b3` | Teal — headers, spinners, active states |
| Text primary   | `#d8dee9` | Warm white                              |
| Text secondary | `#65737e` | Slate — timestamps, metadata            |
| Success        | `#99c794` | Muted emerald                           |
| Warning        | `#fac863` | Warm amber                              |
| Error          | `#ec5f67` | Soft coral red                          |

## Layout tokens

- `TRANSCRIPT_LEFT_INSET`: 2 (reduced from 3 for tighter feel)
- `CALLOUT_PANEL_PADDING`: `(0, 1)` — minimal inner padding
- `ACTIVITY_PANEL_PADDING`: `(0, 0)` — flush activity cards
- `ACTIVITY_BLOCK_BOTTOM_PAD`: `(0, 0, 0, 0)` — maximum density
- Panels use `box.SQUARE` instead of `box.ROUNDED` for an instrumentation look
- Diff syntax highlighting uses the `material` theme instead of `monokai`

## Reasoning / "Thought Stream" chrome

- Reasoning text uses `CLR_THOUGHT_BODY` (`#65737e` slate) with a left gutter marker `┃` to visually distinguish internal thought from tool output
- The streaming cursor uses the thin block character `▌`
- Wrapped continuation lines use a `  ` indent (no gutter) to keep the visual hierarchy clear

## Review checklist for UI changes

- Does this change reuse existing theme/layout tokens?
- Does it preserve status color semantics across prompt + transcript + live panels?
- Does it keep panel title naming consistent?
- Does it avoid adding extra noise to the default prompt?
- Does it keep the same marker set across views?
- For the deep-system-instrumentation preset: are the teal/emerald/coral semantics respected?
