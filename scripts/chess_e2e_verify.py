"""End-to-end verification that the reliability fixes unstick the chess scenario.

Reproduces the exact failure mode observed in
``logs/workspaces/ultimatedemo__9bb5826979f7/app.log`` — Kimi K2.5 emits
over-escaped HTML/CSS (``\\n`` pairs instead of real newlines, ``\\"``
instead of ``"``) via OpenAI-style function calling — and walks each
tool-call payload through the same pipeline the REPL uses:

    repair_arguments_in_place  ->  FileEditor(create_file, ...)

Before the fixes:
    * Tree-sitter rejects the CSS and HTML (ERROR nodes on ``\\n    gap``
      and ``class=\\"...\\">``) -> ``Syntax validation failed`` blocks the
      write -> circuit breaker trips after 5 rejects -> agent gives up.

After the fixes:
    * ``content_escape_repair`` collapses both single- and double-backslash
      residue for strict-markup files -> content hits disk as valid
      HTML/CSS/JS -> chess game is playable.

Run::

    python scripts/chess_e2e_verify.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Make sure we can import the in-tree backend regardless of how the script is run.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.core.content_escape_repair import repair_arguments_in_place
from backend.execution.utils.file_editor import FileEditor


# ---------------------------------------------------------------------------
# Fixture payloads: what Kimi K2.5 produced on the wire. We build them from
# a "clean" source with real newlines/real quotes, then programmatically
# introduce the exact escape residue observed in the logs. This makes the
# Python source readable while preserving the on-the-wire bytes we want to
# feed into the pipeline.
# ---------------------------------------------------------------------------

_INDEX_HTML_CLEAN = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Chess</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body>
  <header>
    <h1>Chess</h1>
    <div id="status">White's turn</div>
    <button id="reset">Reset</button>
  </header>
  <main>
    <div id="board" class="board"></div>
    <aside class="captures">
      <section><h3>Captured White</h3><div id="cap-w" class="cap-row"></div></section>
      <section><h3>Captured Black</h3><div id="cap-b" class="cap-row"></div></section>
    </aside>
  </main>
  <script src="chess.js"></script>
</body>
</html>
"""

# The actual CSS Kimi produced included ``\\n    gap`` residue inside a
# rule body — see app.log line 1308 ("Found: ';\\\\n    gap'"). We bake
# the residue back into a representative rule below so the repair pass
# has to neutralize it.
_STYLES_CSS_CLEAN = """* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; margin: 0; background: #222; color: #eee; }
header { display: flex;__RESIDUE__    gap: 16px; align-items: center; padding: 12px 20px; background: #111; }
header h1 { margin: 0; font-size: 20px; }
#status { flex: 1; font-weight: 600; }
button { padding: 6px 14px; background: #4a90e2; color: white; border: 0; border-radius: 4px; cursor: pointer; }
button:hover { background: #3a7bc8; }
main { display: grid; grid-template-columns: auto 200px; gap: 20px; padding: 20px; }
.board { display: grid; grid-template-columns: repeat(8, 60px); grid-template-rows: repeat(8, 60px); border: 3px solid #555; width: max-content; }
.square { display: flex; align-items: center; justify-content: center; font-size: 40px; cursor: pointer; user-select: none; position: relative; }
.square.light { background: #f0d9b5; color: #333; }
.square.dark { background: #b58863; color: #222; }
.square.selected { outline: 3px solid #ffd700; outline-offset: -3px; }
.square.legal::after { content: ""; width: 14px; height: 14px; border-radius: 50%; background: rgba(0,0,0,0.3); position: absolute; }
.captures { display: flex; flex-direction: column; gap: 10px; }
.cap-row { display: flex; flex-wrap: wrap; gap: 4px; min-height: 40px; background: #333; padding: 6px; border-radius: 4px; font-size: 26px; }
"""

_CHESS_JS_CLEAN = """const INITIAL = [
  ['r','n','b','q','k','b','n','r'],
  ['p','p','p','p','p','p','p','p'],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  ['P','P','P','P','P','P','P','P'],
  ['R','N','B','Q','K','B','N','R']
];
const GLYPH = { K:'\u2654', Q:'\u2655', R:'\u2656', B:'\u2657', N:'\u2658', P:'\u2659',
                k:'\u265A', q:'\u265B', r:'\u265C', b:'\u265D', n:'\u265E', p:'\u265F' };
let board, turn, selected, legalTargets, capturedW, capturedB;

function isWhite(p) { return p && p === p.toUpperCase(); }
function isBlack(p) { return p && p === p.toLowerCase(); }
function inBounds(r, c) { return r >= 0 && r < 8 && c >= 0 && c < 8; }

function pieceMoves(r, c) {
  const p = board[r][c]; if (!p) return [];
  const moves = [];
  const enemy = isWhite(p) ? isBlack : isWhite;
  const push = (rr, cc) => { if (!inBounds(rr, cc)) return false;
    const t = board[rr][cc]; if (!t) { moves.push([rr, cc]); return true; }
    if (enemy(t)) moves.push([rr, cc]); return false; };
  const slide = (dr, dc) => { let rr = r + dr, cc = c + dc;
    while (inBounds(rr, cc)) { if (!push(rr, cc)) break; rr += dr; cc += dc; } };
  const kind = p.toLowerCase();
  if (kind === 'p') {
    const dir = isWhite(p) ? -1 : 1; const start = isWhite(p) ? 6 : 1;
    if (inBounds(r+dir, c) && !board[r+dir][c]) {
      moves.push([r+dir, c]);
      if (r === start && !board[r+2*dir][c]) moves.push([r+2*dir, c]);
    }
    for (const dc of [-1, 1]) {
      const rr = r + dir, cc = c + dc;
      if (inBounds(rr, cc) && board[rr][cc] && enemy(board[rr][cc])) moves.push([rr, cc]);
    }
  } else if (kind === 'n') {
    for (const [dr, dc] of [[-2,-1],[-2,1],[-1,-2],[-1,2],[1,-2],[1,2],[2,-1],[2,1]])
      push(r+dr, c+dc);
  } else if (kind === 'b') {
    for (const [dr, dc] of [[-1,-1],[-1,1],[1,-1],[1,1]]) slide(dr, dc);
  } else if (kind === 'r') {
    for (const [dr, dc] of [[-1,0],[1,0],[0,-1],[0,1]]) slide(dr, dc);
  } else if (kind === 'q') {
    for (const [dr, dc] of [[-1,-1],[-1,1],[1,-1],[1,1],[-1,0],[1,0],[0,-1],[0,1]]) slide(dr, dc);
  } else if (kind === 'k') {
    for (let dr=-1; dr<=1; dr++) for (let dc=-1; dc<=1; dc++)
      if (dr||dc) push(r+dr, c+dc);
  }
  return moves;
}

function render() {
  const el = document.getElementById('board'); el.innerHTML = '';
  for (let r=0; r<8; r++) for (let c=0; c<8; c++) {
    const sq = document.createElement('div');
    sq.className = 'square ' + (((r+c)%2)?'dark':'light');
    sq.textContent = board[r][c] ? GLYPH[board[r][c]] : '';
    sq.dataset.r = r; sq.dataset.c = c;
    if (selected && selected[0]===r && selected[1]===c) sq.classList.add('selected');
    if (legalTargets.some(([rr,cc]) => rr===r && cc===c)) sq.classList.add('legal');
    sq.onclick = () => onClick(r, c);
    el.appendChild(sq);
  }
  document.getElementById('status').textContent = turn === 'w' ? "White's turn" : "Black's turn";
  document.getElementById('cap-w').textContent = capturedW.map(p => GLYPH[p]).join('');
  document.getElementById('cap-b').textContent = capturedB.map(p => GLYPH[p]).join('');
}

function onClick(r, c) {
  const p = board[r][c];
  if (selected) {
    const [sr, sc] = selected;
    if (legalTargets.some(([rr, cc]) => rr === r && cc === c)) {
      const captured = board[r][c];
      if (captured) { (isWhite(captured) ? capturedW : capturedB).push(captured); }
      board[r][c] = board[sr][sc]; board[sr][sc] = null;
      turn = turn === 'w' ? 'b' : 'w';
    }
    selected = null; legalTargets = [];
  } else if (p && ((turn === 'w' && isWhite(p)) || (turn === 'b' && isBlack(p)))) {
    selected = [r, c]; legalTargets = pieceMoves(r, c);
  }
  render();
}

function reset() {
  board = INITIAL.map(row => row.slice());
  turn = 'w'; selected = null; legalTargets = []; capturedW = []; capturedB = [];
  render();
}

document.getElementById('reset').addEventListener('click', reset);
reset();
"""


def _over_escape(clean: str, double_backslash: bool = False) -> str:
    """Return the clean source with real newlines/quotes replaced by escape residue.

    ``double_backslash=False`` models the common Kimi K2.5 single-pass
    over-escape (``\\n`` / ``\\"`` on the wire); ``True`` models the
    "double-escape twice" variant (``\\\\n``) which the original repair
    regex deliberately left alone and which my new strict-markup pass
    now neutralizes.
    """
    if double_backslash:
        # Real newline -> ``\\\\n`` (two backslashes + n)
        newline = '\\\\n'
        quote = '\\\\"'
    else:
        # Real newline -> ``\\n`` (one backslash + n)
        newline = '\\n'
        quote = '\\"'
    return clean.replace('"', quote).replace('\n', newline)


# Build the wire payloads exactly as the failing session emitted them.
# index.html: single-pass over-escape.
_INDEX_HTML_WIRE = _over_escape(_INDEX_HTML_CLEAN, double_backslash=False)

# styles.css: single-pass over-escape AND one surviving ``\\\\n`` chunk
# inside a rule body. This is the pattern that slipped past the old
# conservative regex and left ``display: flex;\\\\n    gap: 4px`` on disk,
# which tree-sitter then rejected. We build it by swapping the sentinel
# for the two-backslash variant, then single-pass over-escaping the rest.
_STYLES_CSS_WIRE = _over_escape(
    _STYLES_CSS_CLEAN.replace('__RESIDUE__', '\x00DOUBLE\x00'),
    double_backslash=False,
).replace('\x00DOUBLE\x00', '\\\\n')

# chess.js: single-pass over-escape (JS is heuristic-repaired).
_CHESS_JS_WIRE = _over_escape(_CHESS_JS_CLEAN, double_backslash=False)


# ---------------------------------------------------------------------------
# Driver -- mirrors the pipeline in backend/engine/function_calling.py
# ---------------------------------------------------------------------------


def _drive_tool_call(editor: FileEditor, *, path: str, wire_content: str) -> dict:
    args = {
        'command': 'create_file',
        'path': path,
        'file_text': wire_content,
    }
    pre_len = len(args['file_text'])
    changes = repair_arguments_in_place(args, path)
    post_len = len(args['file_text'])

    result = editor(
        command='create_file',
        path=path,
        file_text=args['file_text'],
    )
    return {
        'path': path,
        'repair_changes': changes,
        'wire_len': pre_len,
        'repaired_len': post_len,
        'error': result.error,
        'output': result.output,
    }


_FAILED = False


def _assert(cond: bool, msg: str) -> None:
    global _FAILED
    status = 'PASS' if cond else 'FAIL'
    print(f'  [{status}] {msg}')
    if not cond:
        _FAILED = True


def main() -> int:
    workspace = _REPO_ROOT / '_chess_e2e_output'
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir()
    editor = FileEditor(workspace_root=str(workspace))

    print(f'Driving end-to-end tool-call pipeline into: {workspace}\n')

    payloads = [
        ('index.html', _INDEX_HTML_WIRE),
        ('styles.css', _STYLES_CSS_WIRE),
        ('chess.js', _CHESS_JS_WIRE),
    ]

    for path, wire in payloads:
        print(f'--- {path} ---')
        info = _drive_tool_call(editor, path=path, wire_content=wire)
        print(
            f'  wire bytes={info["wire_len"]}, after repair={info["repaired_len"]}, '
            f'repair fields changed={[name for name, _ in info["repair_changes"]]}'
        )
        _assert(
            info['error'] is None,
            f'write succeeded (no pre-write veto) -- got error={info["error"]!r}',
        )

    print('\n--- disk content checks ---')
    html = (workspace / 'index.html').read_text(encoding='utf-8')
    css = (workspace / 'styles.css').read_text(encoding='utf-8')
    js = (workspace / 'chess.js').read_text(encoding='utf-8')

    _assert(
        '<!DOCTYPE html>' in html and html.count('\n') > 5,
        r'index.html has real newlines, not literal \n',
    )
    _assert(
        '\\"' not in html,
        r'index.html has real attribute quotes (no \")',
    )
    _assert(
        '\\n    gap' not in css and '\\\\n    gap' not in css,
        r'styles.css no longer contains literal \n or \\n residue before "gap"',
    )
    _assert(css.count('\n') > 10, 'styles.css has real newlines')
    _assert(js.count('\n') > 20, 'chess.js has real newlines')
    _assert('const INITIAL' in js, 'chess.js preserves JavaScript source tokens')

    print('\n--- first 3 lines ---')
    for p in ('index.html', 'styles.css', 'chess.js'):
        head = '\n    '.join((workspace / p).read_text(encoding='utf-8').splitlines()[:3])
        print(f'  {p}:\n    {head}')

    print('\n--- summary ---')
    if _FAILED:
        print('RESULT: FAIL -- one or more assertions failed.')
        return 1
    print('RESULT: PASS -- all three chess files created from Kimi-style over-escaped input.')
    print(f'               Open {workspace / "index.html"} in a browser to play.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
