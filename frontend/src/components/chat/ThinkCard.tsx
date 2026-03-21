import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { ActionEvent } from "@/types/events";
import { ideCaption } from "./chat-ide-styles";

const panelTrigger =
  "flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[12px] text-muted-foreground transition-colors hover:bg-muted/45";

export function ThoughtTray({ thought }: { thought: string }) {
  const [open, setOpen] = useState(false);

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
        <div className="ml-5 mt-1 border-l-2 border-border/40 pl-3 text-[12px] leading-relaxed text-muted-foreground">
          <p className="whitespace-pre-wrap">{thought}</p>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

interface ThinkCardProps {
  event: ActionEvent;
}

export function ThinkCard({ event }: ThinkCardProps) {
  const [open, setOpen] = useState(false);
  const content = event.message || String(event.args?.thought ?? "");

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className={panelTrigger}>
        <ChevronRight
          className={cn("h-3 w-3 shrink-0 opacity-60 transition-transform duration-200", open && "rotate-90")}
        />
        <Brain className="h-3 w-3 shrink-0 opacity-45" />
        <span className={ideCaption}>Thought</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0">
        <div className="ml-5 mt-1 border-l-2 border-border/40 pl-3 text-[12px] leading-relaxed text-muted-foreground">
          <p className="whitespace-pre-wrap">{content}</p>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
