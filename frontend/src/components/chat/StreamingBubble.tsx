import { MarkdownContent } from "./MarkdownContent";

interface StreamingBubbleProps {
  content: string;
}

export function StreamingBubble({ content }: StreamingBubbleProps) {
  return (
    <div className="max-w-[min(100%,42rem)] text-foreground [&_.prose]:text-[13px] [&_.prose]:leading-[1.65]">
      <MarkdownContent content={content} className="prose-neutral" />
      <span
        className="ml-px inline-block h-[1em] w-px translate-y-px animate-pulse bg-foreground/35 align-middle"
        aria-hidden
      />
    </div>
  );
}
