import { Terminal } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ActionEvent, ObservationEvent } from "@/types/events";
import { ideToolShell, ideCaption } from "./chat-ide-styles";
import { CollapsibleToolOutput } from "./CollapsibleToolOutput";

interface CommandCardProps {
  event: ActionEvent;
}

/** Renders the command that was run (action). */
export function CommandCard({ event }: CommandCardProps) {
  const command = String(event.args?.command ?? "");

  return (
    <div className={cn(ideToolShell, "font-mono")}>
      <div className={cn(ideCaption, "mb-0.5 flex items-center gap-1.5")}>
        <Terminal className="h-3 w-3 opacity-50" />
        <span>Ran</span>
      </div>
      <div className="break-all text-[11px] leading-relaxed text-foreground/90">
        $ {command}
      </div>
    </div>
  );
}

interface CommandOutputCardProps {
  event: ObservationEvent;
}

/** Renders the output of a command (observation) in the conversation stream. */
export function CommandOutputCard({ event }: CommandOutputCardProps) {
  const content = event.content || "";
  const exitCode = event.extras?.exit_code as number | undefined;

  return (
    <div className={cn(ideToolShell, "font-mono")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className={cn(ideCaption, "flex items-center gap-1.5")}>
          <Terminal className="h-3 w-3 opacity-50" />
          <span>Output</span>
        </div>
        {exitCode !== undefined && (
          <Badge
            variant={exitCode === 0 ? "secondary" : "destructive"}
            className="h-5 px-1.5 text-[10px] font-normal"
          >
            exit {String(exitCode)}
          </Badge>
        )}
      </div>
      <CollapsibleToolOutput
        content={content}
        previewLines={5}
        collapseWhenLines={10}
        collapseWhenChars={2000}
        className="mt-1"
        preClassName="rounded border border-border/30 bg-muted/40 p-2 dark:bg-card/35"
      />
    </div>
  );
}
