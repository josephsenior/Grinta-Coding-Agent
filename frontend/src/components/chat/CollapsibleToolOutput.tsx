import { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CollapsibleToolOutputProps {
  content: string;
  /** Lines shown while collapsed (default 5). */
  previewLines?: number;
  /** Collapse when line count exceeds this (default 10). */
  collapseWhenLines?: number;
  /** Also collapse when character count exceeds this (default 2000). */
  collapseWhenChars?: number;
  /** For a single very long line, preview this many characters. */
  singleLineCharPreview?: number;
  className?: string;
  preClassName?: string;
  emptyText?: string;
}

export function CollapsibleToolOutput({
  content,
  previewLines = 5,
  collapseWhenLines = 10,
  collapseWhenChars = 2000,
  singleLineCharPreview = 700,
  className,
  preClassName,
  emptyText = "(no output)",
}: CollapsibleToolOutputProps) {
  const [expanded, setExpanded] = useState(false);

  const { isLong, displayText, lineCount } = useMemo(() => {
    const raw = content ?? "";
    const ls = raw.split("\n");
    const longByLines = ls.length > collapseWhenLines;
    const longByChars = raw.length > collapseWhenChars;
    const long = longByLines || longByChars;

    if (!long || expanded) {
      return { isLong: long, displayText: raw, lineCount: ls.length };
    }

    if (ls.length === 1 && raw.length > singleLineCharPreview) {
      return {
        isLong: true,
        displayText: raw.slice(0, singleLineCharPreview) + "…",
        lineCount: 1,
      };
    }

    const head = ls.slice(0, previewLines).join("\n");
    const truncated = ls.length > previewLines;
    return {
      isLong: true,
      displayText: truncated ? `${head}\n…` : head,
      lineCount: ls.length,
    };
  }, [
    content,
    collapseWhenChars,
    collapseWhenLines,
    expanded,
    previewLines,
    singleLineCharPreview,
  ]);

  const trimmed = (content ?? "").trim();
  if (!trimmed) {
    return (
      <p className={cn("text-[11px] italic text-muted-foreground", className)}>{emptyText}</p>
    );
  }

  return (
    <div className={cn("space-y-1.5", className)}>
      <pre
        className={cn(
          "overflow-x-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-foreground/85",
          expanded && isLong && "max-h-[min(70vh,28rem)] overflow-y-auto",
          !expanded && isLong && "max-h-25 overflow-hidden",
          !isLong && "max-h-52 overflow-y-auto",
          preClassName,
        )}
      >
        {displayText}
      </pre>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((e) => !e)}
          className="flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronRight
            className={cn("h-3 w-3 transition-transform duration-200", expanded && "rotate-90")}
          />
          {expanded
            ? "Show less"
            : lineCount === 1
              ? "Show full output"
              : `Show full output (${lineCount} lines)`}
        </button>
      )}
    </div>
  );
}
