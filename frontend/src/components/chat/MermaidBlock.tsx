import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app-store";

interface MermaidBlockProps {
  chart: string;
}

type MermaidRenderResult = {
  svg: string;
  bindFunctions?: (target: HTMLDivElement | SVGElement) => void;
};

// Cache Mermaid render results by (theme, chart) so React re-renders (e.g. during streaming)
// don't repeatedly call `mermaid.render()` or accidentally clear the container without re-rendering.
const mermaidRenderCache = new Map<string, MermaidRenderResult>();
const mermaidRenderInFlight = new Map<string, Promise<MermaidRenderResult>>();
let lastInitializedTheme: string | null = null;

/**
 * Renders a ```mermaid fenced block from chat markdown as an SVG diagram.
 */
export function MermaidBlock({ chart }: MermaidBlockProps) {
  const reactId = useId().replace(/:/g, "");
  const containerRef = useRef<HTMLDivElement>(null);
  const theme = useAppStore((s) => s.theme);
  const [error, setError] = useState<string | null>(null);
  const renderSeq = useRef(0);

  useEffect(() => {
    const el = containerRef.current;
    const trimmed = chart.trim();
    if (!el) return;

    if (!trimmed) {
      setError(null);
      el.innerHTML = "";
      return;
    }

    let cancelled = false;
    const seq = ++renderSeq.current;
    setError(null);

    const mermaidTheme = theme === "dark" ? "dark" : "default";
    if (lastInitializedTheme !== mermaidTheme) {
      mermaid.initialize({
        startOnLoad: false,
        theme: mermaidTheme,
        securityLevel: "strict",
        fontFamily: "inherit",
      });
      lastInitializedTheme = mermaidTheme;
    }

    const renderKey = `${mermaidTheme}::${trimmed}`;

    const renderId = `mmd-${reactId}-${seq}-${Math.random().toString(36).slice(2, 8)}`;

    void (async () => {
      try {
        const cached = mermaidRenderCache.get(renderKey);
        if (cached) {
          if (cancelled || seq !== renderSeq.current) return;
          const target = containerRef.current;
          if (!target) return;
          target.innerHTML = cached.svg;
          cached.bindFunctions?.(target);
          return;
        }

        const inFlight = mermaidRenderInFlight.get(renderKey);
        const promise =
          inFlight ??
          (async () => {
            const { svg, bindFunctions } = await mermaid.render(renderId, trimmed);
            const result: MermaidRenderResult = { svg, bindFunctions };
            mermaidRenderCache.set(renderKey, result);
            return result;
          })();

        mermaidRenderInFlight.set(renderKey, promise);
        const result = await promise;
        mermaidRenderInFlight.delete(renderKey);

        if (cancelled || seq !== renderSeq.current) return;
        const target = containerRef.current;
        if (!target) return;
        target.innerHTML = result.svg;
        result.bindFunctions?.(target);
      } catch (e) {
        if (!cancelled && seq === renderSeq.current) {
          setError(e instanceof Error ? e.message : String(e));
          if (containerRef.current) containerRef.current.innerHTML = "";
        }
      }
    })();

    return () => {
      cancelled = true;
      el.innerHTML = "";
    };
  }, [chart, reactId, theme]);

  if (!chart.trim()) {
    return null;
  }

  return (
    <div
      className={cn(
        "my-2 overflow-x-auto rounded-md border border-border/50 bg-muted/20 p-3 dark:bg-muted/15",
        "[&_svg]:max-w-full [&_svg]:h-auto",
      )}
    >
      {error && (
        <div className="mb-2 space-y-2">
          <p className="text-[11px] text-destructive">Could not render diagram</p>
          <pre className="overflow-x-auto rounded border border-border/40 bg-muted/45 p-2 font-mono text-[11px] text-muted-foreground dark:bg-card/40">
            {chart.trim()}
          </pre>
        </div>
      )}
      <div
        ref={containerRef}
        className={cn("flex justify-center", error && "hidden")}
        aria-hidden={!!error}
      />
    </div>
  );
}
