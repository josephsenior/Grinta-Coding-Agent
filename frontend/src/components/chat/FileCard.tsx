import { FileText, FilePlus, Pencil } from "lucide-react";
import type { ActionEvent } from "@/types/events";
import { ActionType } from "@/types/agent";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { useParams } from "react-router-dom";
import { getFileContent, getGitDiff } from "@/api/files";
import { toast } from "sonner";

interface FileCardProps {
  event: ActionEvent;
}

export function FileCard({ event }: FileCardProps) {
  const { id: conversationId } = useParams<{ id: string }>();
  const openFile = useContextPanelStore((s) => s.openFile);
  const openDiff = useContextPanelStore((s) => s.openDiff);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const path = String(event.args?.path ?? "");
  const startLine = event.args?.start !== undefined ? Number(event.args.start) : undefined;
  const endLine = event.args?.end !== undefined ? Number(event.args.end) : undefined;

  const lineRange =
    startLine !== undefined && endLine !== undefined
      ? ` (lines ${startLine}-${endLine})`
      : startLine !== undefined
        ? ` (from line ${startLine})`
        : "";

  const handleOpenFile = async () => {
    if (!conversationId || !path) return;
    try {
      const content = await getFileContent(conversationId, path);
      openFile(path, content);
      setContextPanelOpen(true);
    } catch {
      toast.error("Could not load file");
    }
  };

  const handleOpenDiff = async () => {
    if (!conversationId || !path) return;
    try {
      const diff = await getGitDiff(conversationId, path);
      openDiff(path, diff);
      setContextPanelOpen(true);
    } catch {
      toast.error("Could not load diff");
    }
  };

  switch (event.action) {
    case ActionType.READ:
      return (
        <button
          type="button"
          onClick={handleOpenFile}
          className="flex w-full items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground hover:bg-accent transition-colors text-left"
        >
          <FileText className="h-3.5 w-3.5 shrink-0" />
          <span>
            Read <code className="rounded bg-muted px-1 font-mono">{path}</code>
            {lineRange}
          </span>
        </button>
      );

    case ActionType.WRITE:
      return (
        <button
          type="button"
          onClick={handleOpenFile}
          className="flex w-full items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground hover:bg-accent transition-colors text-left"
        >
          <FilePlus className="h-3.5 w-3.5 shrink-0 text-green-500" />
          <span>
            Created <code className="rounded bg-muted px-1 font-mono">{path}</code>
          </span>
        </button>
      );

    case ActionType.EDIT:
      return (
        <div className="rounded-lg border p-2">
          <button
            type="button"
            onClick={handleOpenDiff}
            className="flex w-full items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors text-left"
          >
            <Pencil className="h-3.5 w-3.5 shrink-0 text-yellow-500" />
            <span>
              Edited <code className="rounded bg-muted px-1 font-mono">{path}</code>
            </span>
          </button>
          {event.args?.old_text != null && event.args?.new_text != null && (
            <div className="mt-2 space-y-1 text-xs font-mono">
              <div className="rounded bg-red-500/10 p-1.5 text-red-600 dark:text-red-400">
                <pre className="whitespace-pre-wrap">- {String(event.args.old_text)}</pre>
              </div>
              <div className="rounded bg-green-500/10 p-1.5 text-green-600 dark:text-green-400">
                <pre className="whitespace-pre-wrap">+ {String(event.args.new_text)}</pre>
              </div>
            </div>
          )}
        </div>
      );

    default:
      return null;
  }
}
