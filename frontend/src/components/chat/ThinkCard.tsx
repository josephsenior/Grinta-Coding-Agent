import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { ActionEvent } from "@/types/events";
import { ideCaption } from "./chat-ide-styles";

const panelTrigger =
  "flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[12px] text-muted-foreground transition-colors hover:bg-muted/45";

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s % 60);
  return `${m}m ${rs}s`;
}

export function ThoughtTray({ thought }: { thought: string }) {
  const [open, setOpen] = useState(false);

  // Shared thought tray style with compact status + visible thought content.
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mb-1.5">
      <CollapsibleTrigger className={panelTrigger}>
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 opacity-60 transition-transform duration-200", open && "rotate-90")}
        />
        <Brain className="h-3 w-3 shrink-0 opacity-45" />
        <span className={ideCaption}>Thought</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0">
        <div className="ml-5 mt-1 border-l-2 border-border/40 pl-3 text-[12px] leading-relaxed text-muted-foreground/85">
          <span className="text-[11px] text-muted-foreground/70 italic">thinking</span>
          <div className="mt-1 rounded-md bg-muted/5 px-2 py-1">
            <p className="whitespace-pre-wrap">{thought}</p>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface ThinkCardProps {
  event: ActionEvent;
  durationMs?: number;
}

export function ThinkCard({ event, durationMs }: ThinkCardProps) {
  const [open, setOpen] = useState(false);
  const content = event.message || String(event.args?.thought ?? "");
  const durMs = typeof durationMs === "number" ? durationMs : (event.args as any)?.duration_ms;
  const statusLabel = typeof durMs === "number" ? `finished in ${formatDuration(durMs)}` : "thinking";

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className={panelTrigger}>
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 opacity-60 transition-transform duration-200", open && "rotate-90")}
        />
        <Brain className="h-3 w-3 shrink-0 opacity-45" />
        <span className={ideCaption}>Thought</span>
        <span className="ml-auto text-[11px] text-muted-foreground/80 italic">{statusLabel}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0">
        <div className="ml-5 mt-1 border-l-2 border-border/40 pl-3 text-[12px] leading-relaxed text-muted-foreground/85">
          <span className="text-[11px] text-muted-foreground/70 italic">{statusLabel}</span>
          {content && (
            <div className="mt-1 rounded-md bg-muted/5 px-2 py-1">
              <p className="whitespace-pre-wrap">{content}</p>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
