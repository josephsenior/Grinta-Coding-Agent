import { cn } from "@/lib/utils";
import { MarkdownContent } from "./MarkdownContent";
import type { ActionEvent } from "@/types/events";

interface MessageBubbleProps {
  event: ActionEvent;
}

export function MessageBubble({ event }: MessageBubbleProps) {
  const isUser = event.source === "user";
  const content = event.message || String(event.args?.content ?? "");

  return (
    <div
      className={cn(
        "max-w-[80%] rounded-lg p-3 text-sm",
        isUser
          ? "ml-auto bg-primary text-primary-foreground"
          : "bg-muted",
      )}
    >
      {isUser ? (
        <p className="whitespace-pre-wrap">{content}</p>
      ) : (
        <MarkdownContent content={content} />
      )}
    </div>
  );
}
