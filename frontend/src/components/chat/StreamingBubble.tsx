import { MarkdownContent } from "./MarkdownContent";

interface StreamingBubbleProps {
  content: string;
}

export function StreamingBubble({ content }: StreamingBubbleProps) {
  return (
    <div className="max-w-[80%] rounded-lg bg-muted p-3 text-sm">
      <MarkdownContent content={content} />
      <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-foreground align-middle" />
    </div>
  );
}
