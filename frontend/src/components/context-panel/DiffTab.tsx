import { useContextPanelStore } from "@/stores/context-panel-store";
import { ScrollArea } from "@/components/ui/scroll-area";

export function DiffTab() {
  const filePath = useContextPanelStore((s) => s.diffFilePath);
  const content = useContextPanelStore((s) => s.diffContent);

  if (!filePath || !content) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Click an edit event or git change to view diff
      </div>
    );
  }

  const lines = content.split("\n");

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 shrink-0 items-center border-b px-2">
        <span className="truncate text-xs font-mono text-muted-foreground">
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
