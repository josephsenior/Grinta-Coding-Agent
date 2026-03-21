import { useCallback, useRef } from "react";

export function useColumnResize(options: {
  min: number;
  max: number;
  /** When true, dragging right increases width (left column). When false, dragging left increases width (right column). */
  invertDelta: boolean;
}) {
  const { min, max, invertDelta } = options;
  const dragging = useRef(false);

  return useCallback(
    (e: React.MouseEvent, currentWidth: number, setWidth: (w: number) => void) => {
      e.preventDefault();
      const startX = e.clientX;
      const startW = currentWidth;
      const onMove = (ev: MouseEvent) => {
        const delta = ev.clientX - startX;
        const adjusted = invertDelta ? startW + delta : startW - delta;
        setWidth(Math.max(min, Math.min(max, adjusted)));
      };
      const onUp = () => {
        dragging.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      dragging.current = true;
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [min, max, invertDelta],
  );
}
