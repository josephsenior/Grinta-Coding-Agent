import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { splitAssistantThoughtAndResponse } from "@/lib/assistant-text";
import { cn } from "@/lib/utils";

interface StreamingBubbleProps {
  content: string;
}

export function StreamingBubble({ content }: StreamingBubbleProps) {
  const defaultThoughtOpen =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(min-width: 768px)").matches;
  const [thoughtOpen, setThoughtOpen] = useState(defaultThoughtOpen);

  // If the agent is streaming raw tool-call JSON, extract just the __thought field if possible.
  let displayContent = content;
  if (displayContent.startsWith('{"')) {
    const thoughtMatch = displayContent.match(/"__thought"\s*:\s*"([^]*)/);
    if (thoughtMatch) {
      displayContent = thoughtMatch[1] ?? "";
      // remove trailing broken JSON quotes if we haven't finished the thought
      displayContent = displayContent.replace(/",\s*"[^"]*$/, "");
      displayContent = displayContent.replace(/\\n/g, "\n").replace(/\\"/g, '"');
    }
  }

  const { thought, response, hasSplit } = splitAssistantThoughtAndResponse(displayContent);
  const visibleResponse = response || (!hasSplit ? displayContent : "");
  const cursorTarget = visibleResponse || thought;

  return (
    <div className="max-w-[min(100%,42rem)] text-[13px] leading-[1.65] text-foreground">
      {/* Keep streaming rendering lightweight for smooth token-by-token updates.
          Final assistant messages are still rendered with full Markdown in EventCard. */}
      {thought && (
        <div className="mb-1 border-l-2 border-border/45 pl-3 text-[12px] italic leading-normal text-muted-foreground/80">
          <button
            type="button"
            onClick={() => setThoughtOpen((v) => !v)}
            className="mb-0.5 flex items-center gap-2 text-[10px] uppercase tracking-[0.08em] text-muted-foreground/70 hover:text-muted-foreground"
          >
            <ChevronRight
              className={cn("h-3 w-3 transition-transform", thoughtOpen && "rotate-90")}
            />
            <span className="flex items-center gap-2">
              <span>thinking</span>
              <span className="flex items-center gap-[6px]">
                <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60 animate-pulse" />
                <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/45 animate-pulse delay-75" />
                <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/30 animate-pulse delay-150" />
              </span>
            </span>
          </button>
          {thoughtOpen && (
            <div className="whitespace-pre-wrap wrap-break-word">
              <div className="rounded-md bg-muted/5 px-2 py-1 transition-opacity duration-300 ease-out animate-pulse">
                {thought}
              </div>
            </div>
          )}
        </div>
      )}
      {visibleResponse && (
        <div className="whitespace-pre-wrap wrap-break-word">{visibleResponse}</div>
      )}
      {cursorTarget && (
        <span
          className="ml-px inline-block h-[1em] w-px translate-y-px animate-pulse bg-foreground/35 align-middle"
          aria-hidden
        />
      )}
    </div>
  );
}
