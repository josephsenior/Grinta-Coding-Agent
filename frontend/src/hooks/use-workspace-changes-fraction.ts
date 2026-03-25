import { useCallback, useEffect, useRef, useState } from "react";

/** Right workspace panel (browse view) — changes band height vs tree + preview. */
export const WORKSPACE_BROWSE_CHANGES_FRAC_KEY = "forge-workspace-browse-changes-frac";

const MIN_FRAC = 0.2;
const MAX_FRAC = 0.4;
const DEFAULT_FRAC = 0.3;

function readStoredFrac(storageKey: string): number {
  try {
    const v = localStorage.getItem(storageKey);
    if (v == null) return DEFAULT_FRAC;
    const n = Number.parseFloat(v);
    if (!Number.isFinite(n)) return DEFAULT_FRAC;
    return Math.max(MIN_FRAC, Math.min(MAX_FRAC, n));
  } catch {
    return DEFAULT_FRAC;
  }
}

/** Fraction of the column height for the git changes pane (clamped 0.2–0.4). */
export function useWorkspaceChangesFraction(storageKey: string = WORKSPACE_BROWSE_CHANGES_FRAC_KEY) {
  const [frac, setFrac] = useState(() => readStoredFrac(storageKey));
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setFrac(readStoredFrac(storageKey));
  }, [storageKey]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, String(frac));
    } catch {
      /* ignore */
    }
  }, [frac, storageKey]);

  const onSeparatorPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const h = Math.max(1, rect.height);
      const startY = e.clientY;
      const startFrac = frac;

      const onMove = (ev: PointerEvent) => {
        const dy = ev.clientY - startY;
        const next = Math.max(MIN_FRAC, Math.min(MAX_FRAC, startFrac + dy / h));
        setFrac(next);
      };
      const onUp = () => {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", onUp);
        document.removeEventListener("pointercancel", onUp);
      };
      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", onUp);
      document.addEventListener("pointercancel", onUp);
    },
    [frac],
  );

  return { containerRef, changesFrac: frac, onSeparatorPointerDown };
}
