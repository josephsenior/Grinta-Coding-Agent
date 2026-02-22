import { useState } from "react";
import { ChevronRight, Brain } from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { ActionEvent } from "@/types/events";

interface ThinkCardProps {
  event: ActionEvent;
}

export function ThinkCard({ event }: ThinkCardProps) {
  const [open, setOpen] = useState(false);
  const content = event.message || String(event.args?.thought ?? "");

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg border bg-muted/50 p-3 text-sm text-muted-foreground hover:bg-muted transition-colors">
        <ChevronRight
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-transform",
            open && "rotate-90",
          )}
        />
        <Brain className="h-3.5 w-3.5 shrink-0" />
        <span className="text-left">Thinking...</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-1 rounded-b-lg border border-t-0 bg-muted/30 p-3 text-sm text-muted-foreground">
          <p className="whitespace-pre-wrap">{content}</p>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
