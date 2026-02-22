import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
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
    <div ref={containerRef} className="h-full w-full" />
  );
}
