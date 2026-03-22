import { useEffect, useId, useRef, useState } from "react";
import mermaid from "mermaid";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app-store";

interface MermaidBlockProps {
  chart: string;
}

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

    mermaid.initialize({
      startOnLoad: false,
      theme: theme === "dark" ? "dark" : "default",
      securityLevel: "strict",
      fontFamily: "inherit",
    });

    const renderId = `mmd-${reactId}-${seq}-${Math.random().toString(36).slice(2, 8)}`;

    void (async () => {
      try {
        const { svg, bindFunctions } = await mermaid.render(renderId, trimmed);
        if (cancelled || seq !== renderSeq.current) return;
        const target = containerRef.current;
        if (!target) return;
        target.innerHTML = svg;
        bindFunctions?.(target);
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
