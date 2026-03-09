import { useState, useEffect, useCallback } from "react";
import { GitBranch, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { getGitChanges, getGitDiff } from "@/api/files";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface GitChange {
  status: string;
  path: string;
}

function statusLabel(status: string) {
  switch (status.toUpperCase()) {
    case "M":
      return { label: "M", color: "text-yellow-500", title: "Modified" };
    case "A":
      return { label: "A", color: "text-green-500", title: "Added" };
    case "D":
      return { label: "D", color: "text-red-500", title: "Deleted" };
    case "R":
      return { label: "R", color: "text-blue-500", title: "Renamed" };
    case "C":
      return { label: "C", color: "text-purple-500", title: "Copied" };
    case "U":
      return { label: "U", color: "text-orange-500", title: "Unmerged" };
    default:
      return { label: status, color: "text-muted-foreground", title: status };
  }
}

interface GitChangesProps {
  conversationId: string;
}

export function GitChanges({ conversationId }: GitChangesProps) {
  const [changes, setChanges] = useState<GitChange[]>([]);
  const [loading, setLoading] = useState(false);
  const openDiff = useContextPanelStore((s) => s.openDiff);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const load = useCallback(async () => {
    if (!conversationId) return;
    setLoading(true);
    try {
      const result = await getGitChanges(conversationId);
      setChanges(result);
    } catch {
      toast.error("Could not load git changes");
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleClick = async (change: GitChange) => {
    if (change.status.toUpperCase() === "D") {
      toast.info("File deleted — no diff available");
      return;
    }
    try {
      const diff = await getGitDiff(conversationId, change.path);
      openDiff(change.path, diff);
      setContextPanelOpen(true);
    } catch {
      toast.error("Could not load diff");
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <div className="flex items-center gap-1.5">
          <GitBranch className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
            Changes
          </span>
          {changes.length > 0 && (
            <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
              {changes.length}
            </Badge>
          )}
        </div>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={load} title="Refresh">
          <RefreshCw className="h-3 w-3" />
        </Button>
      </div>
      <ScrollArea className="flex-1">
        <div className="p-1">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : changes.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              Source tree strictly unmodified
            </p>
          ) : (
            changes.map((change) => {
              const { label, color, title } = statusLabel(change.status);
              return (
                <button
                  key={change.path}
                  type="button"
                  onClick={() => handleClick(change)}
                  title={`${title}: ${change.path}`}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-accent transition-colors text-left"
                >
                  <span className={cn("w-3 shrink-0 font-bold font-mono", color)}>
                    {label}
                  </span>
                  <span className="truncate font-mono">{change.path}</span>
                </button>
              );
            })
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
