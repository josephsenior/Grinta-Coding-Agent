const INITIAL = [
  ['r','n','b','q','k','b','n','r'],
  ['p','p','p','p','p','p','p','p'],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  ['P','P','P','P','P','P','P','P'],
  ['R','N','B','Q','K','B','N','R']
];
const GLYPH = { K:'♔', Q:'♕', R:'♖', B:'♗', N:'♘', P:'♙',
                k:'♚', q:'♛', r:'♜', b:'♝', n:'♞', p:'♟' };
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
