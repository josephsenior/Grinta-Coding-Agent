import { useContextPanelStore } from "@/stores/context-panel-store";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

export function DiffTab() {
  const filePath = useContextPanelStore((s) => s.diffFilePath);
  const content = useContextPanelStore((s) => s.diffContent);
  const goToBrowse = useContextPanelStore((s) => s.goToBrowse);

  if (!filePath || !content) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex h-8 shrink-0 items-center border-b px-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs text-muted-foreground"
            onClick={() => goToBrowse()}
          >
            <ArrowLeft className="h-3 w-3" />
            Workspace
          </Button>
        </div>
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Open a diff from an edit card or Changes
        </div>
      </div>
    );
  }

  const lines = content.split("\n");

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 shrink-0 items-center gap-1 border-b px-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0 text-muted-foreground"
          onClick={() => goToBrowse()}
          title="Back to workspace"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </Button>
        <span className="min-w-0 flex-1 truncate text-xs font-mono text-muted-foreground">
          {filePath}
        </span>
      </div>
      <ScrollArea className="flex-1">
        <pre className="p-2 text-xs font-mono leading-5">
          {lines.map((line, i) => {
            let className = "text-foreground";
            if (line.startsWith("+") && !line.startsWith("+++")) {
              className = "bg-green-500/10 text-green-600 dark:text-green-400";
            } else if (line.startsWith("-") && !line.startsWith("---")) {
              className = "bg-red-500/10 text-red-600 dark:text-red-400";
            } else if (line.startsWith("@@")) {
              className = "text-blue-500";
            } else if (line.startsWith("diff") || line.startsWith("index")) {
              className = "text-muted-foreground font-medium";
            }
            return (
              <div key={i} className={className}>
                {line || "\u00A0"}
              </div>
            );
          })}
        </pre>
      </ScrollArea>
    </div>
  );
}
