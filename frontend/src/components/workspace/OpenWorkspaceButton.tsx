import { useState } from "react";
import type { ComponentProps } from "react";
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
import { cn } from "@/lib/utils";

type ButtonProps = ComponentProps<typeof Button>;

export interface OpenWorkspaceButtonProps extends ButtonProps {
  /** When true, show folder icon + default label (overridable via children). */
  showIcon?: boolean;
}

/**
 * Opens the path dialog and applies the workspace via API.
 * Shared by the workspace folder bar and the empty-state panel.
 */
export function OpenWorkspaceButton({
  showIcon = true,
  children = "Open workspace",
  className,
  onClick,
  ...buttonProps
}: OpenWorkspaceButtonProps) {
  const { data } = useWorkspace();
  const setWorkspace = useSetWorkspace();

  const [openOpen, setOpenOpen] = useState(false);
  const [openPath, setOpenPath] = useState("");

  const path = data?.path ?? null;

  return (
    <>
      <Button
        type="button"
        className={cn(showIcon && "gap-2", className)}
        {...buttonProps}
        onClick={(e) => {
          onClick?.(e);
          if (e.defaultPrevented) return;
          setOpenPath(path ?? "");
          setOpenOpen(true);
        }}
      >
        {showIcon ? <FolderOpen className="h-3.5 w-3.5 shrink-0" /> : null}
        {children}
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
    </>
  );
}
