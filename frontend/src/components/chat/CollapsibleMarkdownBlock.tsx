import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./MarkdownContent";

interface CollapsibleMarkdownBlockProps {
  content: string;
  label?: string;
  previewChars?: number;
  previewLines?: number;
  className?: string;
  showStreamingCursor?: boolean;
}

export function CollapsibleMarkdownBlock({
  content,
  label = "response",
  previewChars = 1400,
  previewLines = 26,
  className,
  showStreamingCursor = false,
}: CollapsibleMarkdownBlockProps) {
  const [open, setOpen] = useState(false);
  const lineCount = content.split("\n").length;
  const isLong = content.length > previewChars || lineCount > previewLines;

  if (!isLong) {
    return (
      <div className={className}>
        <MarkdownContent content={content} />
        {showStreamingCursor && (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-foreground align-middle" />
        )}
      </div>
    );
  }

  // Split into visible preview and the hidden remainder
  const clippedPreview = content.slice(0, previewChars).trimEnd();

  return (
    <Collapsible open={open} onOpenChange={setOpen} className={className}>
      <div>
        <MarkdownContent content={open ? content : `${clippedPreview}\n...`} />
        {showStreamingCursor && !open && (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-foreground align-middle" />
        )}
      </div>
      <div className="mt-2">
        <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
          <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
          {open ? `Collapse ${label}` : `Show full ${label}`}
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent>
        {/* Expanded content is rendered above in the main div when open=true.
            This placeholder ensures Radix animates the height transition. */}
        <div className="h-px" />
      </CollapsibleContent>
    </Collapsible>
  );
}
