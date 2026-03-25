import { useMemo, useState } from "react";
import { BrainCircuit, Book, Edit } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSessionStore } from "@/stores/session-store";
import { ActionType } from "@/types/agent";
import type { ActionEvent } from "@/types/events";

interface ContextItem {
  path: string;
  type: "read" | "edit" | "write";
  timestamp: string;
}

export function ContextRadarTab() {
  const events = useSessionStore((s) => s.events);
  const [filter, setFilter] = useState<"all" | ContextItem["type"]>("all");

  const files = useMemo(() => {
    const contextFiles = new Map<string, ContextItem>();

    events.forEach((e) => {
      if (!("action" in e)) return;
      const actionEvent = e as ActionEvent;

      let path = (actionEvent.args?.path as string) || (actionEvent.args?.file_path as string);

      if (!path) return;

      let type: ContextItem["type"] | null = null;
      switch (actionEvent.action) {
        case ActionType.READ:
          type = "read";
          break;
        case ActionType.EDIT:
          type = "edit";
          break;
        case ActionType.WRITE:
          type = "write";
          break;
      }

      if (type) {
        contextFiles.set(path, {
          path,
          type,
          timestamp: actionEvent.timestamp,
        });
      }
    });

    return Array.from(contextFiles.values()).sort((a, b) =>
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length]);

  const filteredFiles = useMemo(
    () => (filter === "all" ? files : files.filter((file) => file.type === filter)),
    [files, filter],
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <BrainCircuit className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Context Radar
        </span>
        {filteredFiles.length > 0 && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
            {filteredFiles.length}
          </Badge>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1 border-b px-2 py-1.5">
        {(["all", "read", "edit", "write"] as const).map((value) => (
          <Button
            key={value}
            type="button"
            size="sm"
            variant={filter === value ? "secondary" : "ghost"}
            className="h-6 px-2 text-[10px] uppercase tracking-wide"
            onClick={() => setFilter(value)}
          >
            {value}
          </Button>
        ))}
      </div>
      <ScrollArea className="flex-1">
        <div className="p-1">
          {filteredFiles.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              {files.length === 0 ? "No files in context yet" : "No matches for this filter"}
            </p>
          ) : (
            filteredFiles.map((file, idx) => (
              <div
                key={`${file.path}-${idx}`}
                className="flex flex-col gap-1 rounded px-2 py-2 hover:bg-accent transition-colors"
              >
                <div className="flex items-start gap-2">
                  {file.type === "read" && <Book className="h-3.5 w-3.5 shrink-0 text-blue-500" />}
                  {file.type === "edit" || file.type === "write" ? <Edit className="h-3.5 w-3.5 shrink-0 text-amber-500" /> : null}
                  
                  <span className="flex-1 text-xs break-all font-mono leading-tight">
                    {file.path}
                  </span>
                  
                  <Badge variant="outline" className="h-4 shrink-0 px-1 text-[9px] uppercase tracking-wider">
                    {file.type}
                  </Badge>
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}