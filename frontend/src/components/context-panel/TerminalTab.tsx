import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import "@xterm/xterm/css/xterm.css";

const DARK_THEME = {
  background: "#09090b",
  foreground: "#fafafa",
  cursor: "#fafafa",
  selectionBackground: "#264f78",
};

const LIGHT_THEME = {
  background: "#ffffff",
  foreground: "#1e1e1e",
  cursor: "#1e1e1e",
  selectionBackground: "#add6ff",
};

export function TerminalTab() {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const writtenCountRef = useRef(0);

  const terminalLines = useContextPanelStore((s) => s.terminalLines);
  const clearTerminal = useContextPanelStore((s) => s.clearTerminal);
  const appTheme = useAppStore((s) => s.theme);

  // Initialize terminal
  useEffect(() => {
    if (!containerRef.current) return;

    const fit = new FitAddon();
    const term = new Terminal({
      fontSize: 12,
      fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
      theme: appTheme === "dark" ? DARK_THEME : LIGHT_THEME,
      disableStdin: true,
      convertEol: true,
      scrollback: 5000,
      cursorBlink: false,
    });

    term.loadAddon(fit);
    term.open(containerRef.current);

    // Small delay for container to get dimensions
    requestAnimationFrame(() => {
      try { fit.fit(); } catch { /* ignore initial fit errors */ }
    });

    termRef.current = term;
    fitRef.current = fit;
    writtenCountRef.current = 0;

    const resizeObserver = new ResizeObserver(() => {
      try { fit.fit(); } catch { /* ignore */ }
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Update theme
  useEffect(() => {
    if (termRef.current) {
      termRef.current.options.theme = appTheme === "dark" ? DARK_THEME : LIGHT_THEME;
    }
  }, [appTheme]);

  // Write new lines
  useEffect(() => {
    if (!termRef.current) return;
    const term = termRef.current;
    for (let i = writtenCountRef.current; i < terminalLines.length; i++) {
      const line = terminalLines[i];
      if (line !== undefined) term.writeln(line);
    }
    writtenCountRef.current = terminalLines.length;
  }, [terminalLines]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex h-8 shrink-0 items-center justify-between border-b border-border/50 px-2">
        <div className="text-[11px] text-muted-foreground">Live terminal output</div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] tabular-nums text-muted-foreground/80">{terminalLines.length} lines</span>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-[10px]"
            onClick={clearTerminal}
            disabled={terminalLines.length === 0}
          >
            Clear
          </Button>
        </div>
      </div>
      <div className="relative min-h-0 flex-1">
        {terminalLines.length === 0 && (
          <div className="absolute inset-0 z-10 flex items-center justify-center text-center text-[11px] text-muted-foreground/80">
            Terminal output will appear here when the agent runs commands.
          </div>
        )}
        <div ref={containerRef} className="h-full w-full" />
      </div>
    </div>
  );
}
