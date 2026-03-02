import { useMemo, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";

interface CardCollapsibleSectionProps {
  label: string;
  lines: string[];
  previewLines?: number;
  className?: string;
}

export function CardCollapsibleSection({
  label,
  lines,
  previewLines = 12,
  className,
}: CardCollapsibleSectionProps) {
  const [open, setOpen] = useState(false);
  const isLong = lines.length > previewLines;

  const previewText = useMemo(() => {
    if (!isLong || open) return lines.join("\n");
    return `${lines.slice(0, previewLines).join("\n")}\n...`;
  }, [isLong, lines, open, previewLines]);

  if (!isLong) {
    return (
      <pre className={cn("max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs", className)}>
        {lines.join("\n")}
      </pre>
    );
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <pre className={cn("max-h-48 overflow-auto whitespace-pre-wrap font-mono text-xs", className)}>
        {previewText}
      </pre>
      <div className="mt-2">
        <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors">
          <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
          {open ? `Collapse ${label}` : `Show all ${lines.length} lines`}
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent />
    </Collapsible>
  );
}
