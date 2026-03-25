import { useWorkspace } from "@/hooks/use-workspace";
import { OpenWorkspaceButton } from "./OpenWorkspaceButton";

function shortenPath(path: string, maxLen = 52): string {
  if (path.length <= maxLen) return path;
  const start = path.slice(0, 24);
  const end = path.slice(-22);
  return `${start}…${end}`;
}

/** Current project path + open / change folder (only shown once a workspace is set). */
export function WorkspaceFolderBar() {
  const { data, isLoading } = useWorkspace();

  const path = data?.path ?? null;
  const displayPath = path ?? "";

  return (
    <div className="flex shrink-0 flex-col gap-1.5 border-b border-border/40 bg-muted/20 px-2 py-2">
      <div className="min-w-0">
        <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          Project folder
        </p>
        <p
          className="truncate font-mono text-[11px] text-foreground/90"
          title={displayPath || "No folder open"}
        >
          {isLoading ? "…" : path ? shortenPath(path) : "—"}
        </p>
      </div>
      <OpenWorkspaceButton
        variant="secondary"
        size="sm"
        className="h-7 gap-1 text-[11px]"
      />
    </div>
  );
}
