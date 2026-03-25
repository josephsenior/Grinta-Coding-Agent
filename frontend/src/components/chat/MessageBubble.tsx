import { cn } from "@/lib/utils";
import { splitAssistantThoughtAndResponse } from "@/lib/assistant-text";
import { MarkdownContent } from "./MarkdownContent";
import type { ActionEvent } from "@/types/events";

interface MessageBubbleProps {
  event: ActionEvent;
}

export function MessageBubble({ event }: MessageBubbleProps) {
  const isUser = event.source === "user";
  const rawContent = event.message || String(event.args?.content ?? "");
  const segments = isUser
    ? { thought: "", response: rawContent, hasSplit: false }
    : splitAssistantThoughtAndResponse(rawContent);
  const thought = segments.thought;
  const content = segments.response || (segments.hasSplit ? "" : rawContent);

  return (
    <div
      className={cn(
        "w-full text-[13px] leading-[1.65]",
        isUser ? "flex justify-end" : "max-w-[min(100%,42rem)]",
      )}
    >
      {isUser ? (
        <div className="max-w-[min(100%,85%)] rounded-lg border border-border/50 bg-muted/60 px-3 py-2 text-foreground shadow-none dark:bg-muted/40">
          <p className="whitespace-pre-wrap">{content}</p>
        </div>
      ) : (
        <div className="space-y-2 text-foreground [&_.prose]:text-[13px] [&_.prose]:leading-[1.65]">
          {thought && (
            <div className="border-l-2 border-border/45 pl-3 text-[12px] italic leading-[1.55] text-muted-foreground/85">
              <p className="whitespace-pre-wrap">{thought}</p>
            </div>
          )}
          {content && <MarkdownContent content={content} className="prose-neutral" />}
        </div>
      )}
    </div>
  );
}
