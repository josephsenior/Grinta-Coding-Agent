import { useState } from "react";
import { FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useSetWorkspace, useWorkspace } from "@/hooks/use-workspace";

function shortenPath(path: string, maxLen = 52): string {
  if (path.length <= maxLen) return path;
  const start = path.slice(0, 24);
  const end = path.slice(-22);
  return `${start}…${end}`;
}

/** Single action: open a project folder (path is whatever the user enters). */
export function WorkspaceFolderBar() {
  const { data, isLoading } = useWorkspace();
  const setWorkspace = useSetWorkspace();

  const [openOpen, setOpenOpen] = useState(false);
  const [openPath, setOpenPath] = useState("");

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
          {isLoading
            ? "…"
            : path
              ? shortenPath(path)
              : "No folder open — choose one to start"}
        </p>
      </div>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        className="h-7 gap-1 text-[11px]"
        onClick={() => {
          setOpenPath(path ?? "");
          setOpenOpen(true);
        }}
      >
        <FolderOpen className="h-3.5 w-3.5 shrink-0" />
        Open workspace
      </Button>

      <Dialog open={openOpen} onOpenChange={setOpenOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Open workspace</DialogTitle>
            <DialogDescription>
              Absolute path to your project directory on the machine where the Forge backend runs
              (copy from File Explorer on Windows, or paste a path on macOS/Linux).
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-2 py-2">
            <label htmlFor="ws-open-path" className="text-sm font-medium">
              Folder path
            </label>
            <Input
              id="ws-open-path"
              value={openPath}
              onChange={(e) => setOpenPath(e.target.value)}
              placeholder="C:\Users\you\projects\my-app"
              className="font-mono text-xs"
              autoComplete="off"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setOpenOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              disabled={!openPath.trim() || setWorkspace.isPending}
              onClick={() =>
                setWorkspace.mutate(openPath.trim(), {
                  onSettled: () => setOpenOpen(false),
                })
              }
            >
              {setWorkspace.isPending ? "Applying…" : "Use this folder"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
