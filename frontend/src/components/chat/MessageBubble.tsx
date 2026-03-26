import { cn } from "@/lib/utils";
import { splitAssistantThoughtAndResponse } from "@/lib/assistant-text";
import { MarkdownContent } from "./MarkdownContent";
import type { ActionEvent } from "@/types/events";

interface MessageBubbleProps {
  event: ActionEvent;
  thoughtDurationMs?: number;
}

function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s % 60);
  return `${m}m ${rs}s`;
}

export function MessageBubble({ event, thoughtDurationMs }: MessageBubbleProps) {
  const isUser = event.source === "user";
  const rawContent = event.message || String(event.args?.content ?? "");
  const segments = isUser
    ? { thought: "", response: rawContent, hasSplit: false }
    : splitAssistantThoughtAndResponse(rawContent);
  const thought = segments.thought;
  const content = segments.response || (segments.hasSplit ? "" : rawContent);
  const showThoughtMeta = !!thought || typeof thoughtDurationMs === "number";

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
          {showThoughtMeta && (
            <div className="border-l-2 border-border/45 pl-3 text-[12px] italic leading-[1.55] text-muted-foreground/85">
              <span className="text-[11px] leading-[1.2] text-muted-foreground/75 italic">
                {typeof thoughtDurationMs === "number"
                  ? `finished in ${formatDuration(thoughtDurationMs)}`
                  : "thinking"}
              </span>
              {thought && (
                <div className="mt-1 rounded-md bg-muted/5 px-2 py-1">
                  <p className="whitespace-pre-wrap">{thought}</p>
                </div>
              )}
            </div>
          )}
          {content && <MarkdownContent content={content} className="prose-neutral" />}
        </div>
      )}
    </div>
  );
}
