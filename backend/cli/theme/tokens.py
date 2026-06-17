"""Default Rich / prompt_toolkit color and style tokens."""

from __future__ import annotations

# ── Backgrounds ────────────────────────────────────────────────────────────────
HUD_BG = '#0f1525'  # HUD footer background (slightly lighter than main bg)

# ── Separators & borders ───────────────────────────────────────────────────────
CLR_SEP = '#1b233a'  # bullet separator and lightweight dividers
CLR_CARD_BORDER = '#1b233a'  # rounded card / panel border (navy)

# ── HUD display text ──────────────────────────────────────────────────────────
CLR_HUD_MODEL = 'bold #e9e9e9'  # model name (near-white)
CLR_HUD_DETAIL = '#969aad'  # tokens, cost, calls (cool gray)
CLR_META = '#969aad'  # subdued metadata, timers, helper text
CLR_MUTED_TEXT = '#1b233a'  # long-form secondary labels / values
CLR_BRAND = 'bold #91abec'  # GRINTA wordmark / active spinner hue
CLR_BRAND_HUE = '#91abec'  # brand blue without bold modifier

# ── Status semantic colors (HUD ledger / footer badges) ──────────────────────
CLR_STATUS_OK = '#54efae'  # Healthy / Ready (bright green)
CLR_STATUS_WARN = '#f6ff8f'  # Review / Paused (lime yellow)
CLR_STATUS_ERR = '#fd8383'  # Error (soft red)

# ── Result tones (paired body/icon hues for activity rows + tone panels) ─────
CLR_OK_BODY = '#54efae'  # success body text
CLR_OK_ICON = 'bold #54efae'  # success icon / accent
CLR_ERR_BODY = '#fd8383'  # error body text
CLR_ERR_ICON = 'bold #fd8383'  # error icon / accent
CLR_WARN_BODY = '#f6ff8f'  # warning body text
CLR_WARN_ICON = 'bold #f6ff8f'  # warning icon / accent
CLR_INFO_BODY = '#91abec'  # info body text
CLR_INFO_ICON = 'bold #91abec'  # info icon / accent
CLR_NOTICE_BG = '#12161f'  # soft transcript notice background
CLR_NOTICE_TEXT = '#7a8299'  # dim transcript notice body text

# ── Shell output chrome ────────────────────────────────────────────────────────
CLR_SHELL_OUTPUT = '#6b7280'  # shell command output text (dim gray)
CLR_SHELL_BORDER = '#374151'  # shell output left border line

# ── Shared UI markers (keep iconography consistent) ───────────────────────────
MARK_OK = '✓'
MARK_ERR = '✗'
MARK_WARN = '⚠'
MARK_INFO = '•'
MARK_PROMPT = '❯'

# ── Shared Rich style aliases (avoid scattered literals) ─────────────────────
STYLE_DIM = 'dim'
STYLE_DEFAULT = 'default'
STYLE_BOLD = 'bold'
STYLE_BOLD_DIM = 'bold #969aad'
STYLE_ITALIC_DIM = 'dim italic'
STYLE_EMPTY = ''

# ── Activity card chrome ──────────────────────────────────────────────────────
CLR_CARD_TITLE = 'bold #91abec'  # panel title text (periwinkle blue)

# ── Activity row text ─────────────────────────────────────────────────────────
CLR_VERB = 'bold #91abec'  # action verb (periwinkle blue)
CLR_DETAIL = '#e9e9e9'  # action detail (near-white)
CLR_SECONDARY = '#969aad'  # secondary row (cool gray)
CLR_SECONDARY_OK = 'dim #54efae'  # secondary row (success)
CLR_SECONDARY_ERR = 'dim #fd8383'  # secondary row (error)

# ── Diff colors ───────────────────────────────────────────────────────────────
CLR_DIFF_ADD = '#54efae'  # added lines (bright green)
CLR_DIFF_REM = '#fd8383'  # removed lines (soft red)
CLR_DIFF_ADD_DIM = 'dim #54efae'  # added lines delta (secondary line)
CLR_DIFF_REM_DIM = 'dim #fd8383'  # removed lines delta (secondary line)

# ── Inline Rich markup ────────────────────────────────────────────────────────
MSG_STYLE_SUCCESS_MARK = 'bold #54efae'  # short ✓ success flashes (onboarding)
MSG_STYLE_PROVIDER_HINT = '#91abec'  # provider name in onboarding lines

# ── System message tags (panels / notices) ────────────────────────────────────
STYLE_SYSTEM_TAG_WARNING = '#f6ff8f'
STYLE_SYSTEM_TAG_AUTONOMY = '#91abec'
STYLE_SYSTEM_TAG_STATUS = '#54efae'
STYLE_SYSTEM_TAG_SETTINGS = '#91abec'
STYLE_SYSTEM_TAG_SYSTEM = '#91abec'
STYLE_SYSTEM_TAG_TIMEOUT = '#f6ff8f'
STYLE_SYSTEM_TAG_NOTE = '#91abec'

# ── Delegate worker row accents ────────────────────────────────────────────────
STYLE_DELEGATE_STARTING = '#91abec'
STYLE_DELEGATE_RUNNING = '#f6ff8f'
STYLE_DELEGATE_DONE = '#54efae'
STYLE_DELEGATE_FAILED = '#fd8383'

# ── Worker live-panel chrome ──────────────────────────────────────────────────
CLR_WORKER_SPINNER = '#91abec'  # spinner during delegation (matches brand blue)
CLR_WORKER_TIMER = '#969aad'  # worker elapsed timer
CLR_WORKER_LABEL = 'bold #e9e9e9'  # worker name/label
CLR_WORKER_ACTION = '#969aad'  # last action / reasoning line
CLR_WORKER_LABEL_DONE = 'bold #54efae'  # completed worker label
CLR_WORKER_LABEL_FAILED = 'bold #fd8383'  # failed worker label
CLR_WORKER_BORDER = '#1b233a'  # worker card border (navy)

# ── Reasoning / thinking chrome ────────────────────────────────────────────────
CLR_SPINNER = '#91abec'  # spinner icon (matches brand blue)
CLR_ACTION = 'bold #e9e9e9'  # current action label text
CLR_THINKING_BORDER = '#1b233a'  # reasoning / live panel border accent (navy)
CLR_LIVE_PANEL_BORDER = '#1b233a'  # Live Rich block border
CLR_THOUGHT_BODY = '#65737e'  # Live Thinking + flushed reasoning snapshot
CLR_REASONING_SNAP = CLR_THOUGHT_BODY  # legacy alias; keep in sync
CLR_DRAFT_BORDER = '#91abec'  # draft reply preview border accent (brand blue)
CLR_DECISION_BORDER = '#f6ff8f'  # approval / question / options accent (lime yellow)
CLR_USER_BORDER = 'dim #91abec'  # user message panel border (brand blue dim)
CLR_USER_BG = 'on #131724'  # user message panel background
CLR_STATE_RUNNING = '#91abec bold'  # running / active state badge (brand blue)
CLR_AUTONOMY_BALANCED = '#54efae'  # balanced autonomy tag
CLR_AUTONOMY_FULL = '#f6ff8f bold'  # full autonomy tag (lime yellow)
CLR_AUTONOMY_CONSERVATIVE = '#91abec bold'  # conservative autonomy (blue)

# ── Orient tool gutter ────────────────────────────────────────────────────────
CLR_ORIENT_GUTTER = '#5a6a8a'  # dim blue-gray — orient tool icon/verb gutter

# ── Error transcript block chrome (matches thinking/orient layout) ─────────────
CLR_ERROR_PIPE = '#5a2d2d'  # left gutter pipe
CLR_ERROR_PREFIX = '#fd8383'  # "Error:" label
CLR_ERROR_BODY = 'dim #fd8383'  # error detail body

# ── Section divider ────────────────────────────────────────────────────────────
CLR_SECTION_RULE = '#32416a'  # "Tools & commands" divider rule

# ── Confirmation UI ────────────────────────────────────────────────────────────
CLR_RISK_HIGH = 'bold #fd8383'
CLR_RISK_MEDIUM = '#f6ff8f'
CLR_RISK_LOW = '#54efae'
CLR_RISK_ASK = '#f6ff8f'

# ── Decision callouts ─────────────────────────────────────────────────────────
CLR_QUESTION_TEXT = '#f6ff8f'  # question / escalation prose body
CLR_OPTION_TEXT = '#e9e9e9'  # neutral option label body
CLR_OPTION_RECOMMENDED = '#f6ff8f'  # recommended option marker

# ── Secondary panels ──────────────────────────────────────────────────────────
CLR_OUTPUT_PANEL_BORDER = '#1b233a'  # nested terminal output panel
CLR_OUTPUT_PANEL_TITLE = 'dim #969aad'  # nested panel title (session id, lines)

# ── Reasoning / activity rule chrome ─────────────────────────────────────────
CLR_REASONING_COMMITTED = CLR_THOUGHT_BODY  # transcript snapshot (same as live body)
CLR_TURN_RULE = 'dim #969aad'  # "Activity" rule above first tool row
CLR_RECOVERY_HINT = '#91abec'  # "Next steps" headline body in recovery notice
CLR_RECOVERY_HINT_DIM = 'dim #91abec'  # recovery body / numbered steps

# ── Splash branding ────────────────────────────────────────────────────────────
CLR_SPLASH_LOGO_ACCENT = '#91abec'  # logo block art (brand blue)
CLR_SPLASH_FIGLET = 'bold #91abec'  # large GRINTA wordmark on the splash (blue)

# ── prompt_toolkit (``Style.from_dict``) ──────────────────────────────────────
PT_DEFAULT_FG = '#e9e9e9'
PT_PLACEHOLDER_DIM = '#1b233a'
PT_FOOTER_BADGE_BRACKET = '#1b233a'
PT_FOOTER_BADGE_CORE = 'bold #91abec'
PT_FOOTER_KICKER = 'bold #91abec'
PT_FOOTER_WARN_BRACKET = '#3d1f1f'
PT_FOOTER_WARN_CORE = 'bold #f6ff8f'
PT_FOOTER_WARN_KICKER = 'bold #f6ff8f'
PT_FOOTER_WARN_SEP = '#3d1f1f'
PT_COMPLETION_MENU_BG = 'bg:#0f1525 #969aad'
PT_COMPLETION_MENU_CURRENT = 'bg:#1b233a bold #91abec'
PT_COMPLETION_META_BG = 'bg:#0a0e1b #969aad'
PT_COMPLETION_META_CURRENT = 'bg:#1b233a #91abec'
PT_SCROLLBAR_BG = 'bg:#0a0e1b'
PT_SCROLLBAR_BUTTON = 'bg:#1b233a'
