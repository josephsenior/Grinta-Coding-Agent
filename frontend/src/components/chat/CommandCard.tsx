import { useState } from "react";
import { Terminal, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import type { ActionEvent, ObservationEvent } from "@/types/events";

interface CommandCardProps {
  event: ActionEvent;
}

/** Renders the command that was run (action). */
export function CommandCard({ event }: CommandCardProps) {
  const command = String(event.args?.command ?? "");
  const appendTerminalOutput = useContextPanelStore((s) => s.appendTerminalOutput);
  const setActiveTab = useContextPanelStore((s) => s.setActiveTab);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const handleClick = () => {
    appendTerminalOutput(`$ ${command}`);
    setActiveTab("terminal");
    setContextPanelOpen(true);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className="flex w-full items-start gap-2 rounded-lg border bg-zinc-950 p-3 text-xs font-mono text-green-400 hover:bg-zinc-900 transition-colors text-left"
    >
      <Terminal className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="break-all">$ {command}</span>
    </button>
  );
}

interface CommandOutputCardProps {
  event: ObservationEvent;
}

const OUTPUT_COLLAPSE_LINES = 20;

/** Renders the output of a command (observation) — also pushes to terminal store. */
export function CommandOutputCard({ event }: CommandOutputCardProps) {
  const content = event.content || "";
  const exitCode = event.extras?.exit_code as number | undefined;
  const lines = content.split("\n");
  const isLong = lines.length > OUTPUT_COLLAPSE_LINES;
  const [expanded, setExpanded] = useState(false);

  const appendTerminalOutput = useContextPanelStore((s) => s.appendTerminalOutput);
  const setActiveTab = useContextPanelStore((s) => s.setActiveTab);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const handleClick = () => {
    appendTerminalOutput(content);
    setActiveTab("terminal");
    setContextPanelOpen(true);
  };

  const displayContent =
    isLong && !expanded
      ? lines.slice(0, OUTPUT_COLLAPSE_LINES).join("\n") + "\n..."
      : content;

  if (isLong) {
    return (
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <button
          type="button"
          onClick={handleClick}
          className="w-full rounded-t-lg border bg-zinc-950 px-3 pt-3 text-left hover:bg-zinc-900 transition-colors"
        >
          <pre className="max-h-60 overflow-auto whitespace-pre-wrap font-mono text-xs text-zinc-300">
            {displayContent}
          </pre>
          <div className="mt-2 flex items-center gap-2 pb-2">
            {exitCode !== undefined && (
              <Badge variant={exitCode === 0 ? "success" : "destructive"}>
                exit {String(exitCode)}
              </Badge>
            )}
            <CollapsibleTrigger
              onClick={(e) => e.stopPropagation()}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronRight
                className={cn("h-3 w-3 transition-transform", expanded && "rotate-90")}
              />
              {expanded ? "Collapse" : `Show all ${lines.length} lines`}
            </CollapsibleTrigger>
          </div>
        </button>
        <CollapsibleContent />
      </Collapsible>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className="w-full rounded-lg border bg-zinc-950 p-3 text-left hover:bg-zinc-900 transition-colors"
    >
      <pre className="max-h-60 overflow-auto whitespace-pre-wrap font-mono text-xs text-zinc-300">
        {content}
      </pre>
      {exitCode !== undefined && (
        <Badge
          variant={exitCode === 0 ? "success" : "destructive"}
          className="mt-2"
        >
          exit {String(exitCode)}
        </Badge>
      )}
    </button>
  );
}
