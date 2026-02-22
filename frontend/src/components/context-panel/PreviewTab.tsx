import { ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useContextPanelStore } from "@/stores/context-panel-store";

export function PreviewTab() {
  const previewUrl = useContextPanelStore((s) => s.previewUrl);

  if (!previewUrl) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        No web preview available
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 shrink-0 items-center justify-between border-b px-2">
        <span className="truncate text-xs font-mono text-muted-foreground">
          {previewUrl}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          asChild
        >
          <a href={previewUrl} target="_blank" rel="noopener noreferrer">
            <ExternalLink className="h-3 w-3" />
          </a>
        </Button>
      </div>
      <div className="flex-1">
        <iframe
          src={previewUrl}
          title="Web Preview"
          className="h-full w-full border-0"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
        />
      </div>
    </div>
  );
}
