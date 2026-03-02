import { FileText, FilePlus, Pencil } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ActionEvent } from "@/types/events";
import { ActionType } from "@/types/agent";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { useParams } from "react-router-dom";
import { getFileContent, getGitDiff } from "@/api/files";
import { toast } from "sonner";
import { CardCollapsibleSection } from "./CardCollapsibleSection";
import { CardSectionLabel } from "./CardSectionLabel";

interface FileCardProps {
  event: ActionEvent;
}

export function FileCard({ event }: FileCardProps) {
  const oldText = event.args?.old_text != null ? String(event.args.old_text) : "";
  const newText = event.args?.new_text != null ? String(event.args.new_text) : "";

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
          className="w-full rounded-lg border p-1.5 text-xs text-left text-muted-foreground hover:bg-accent transition-colors"
        >
          <CardSectionLabel
            label="File Read"
            icon={<FileText className="h-3.5 w-3.5 shrink-0" />}
          />
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
          className="w-full rounded-lg border p-1.5 text-xs text-left text-muted-foreground hover:bg-accent transition-colors"
        >
          <CardSectionLabel
            label="File Create"
            icon={<FilePlus className="h-3.5 w-3.5 shrink-0 text-green-500" />}
          />
          <span>
            Created <code className="rounded bg-muted px-1 font-mono">{path}</code>
          </span>
        </button>
      );

    case ActionType.EDIT:
      return (
        <div className="rounded-lg border p-1.5">
          <div className="flex w-full items-center justify-between">
            <button
              type="button"
              onClick={handleOpenDiff}
              className="text-left text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <CardSectionLabel
                label="File Edit"
                icon={<Pencil className="h-3.5 w-3.5 shrink-0 text-yellow-500" />}
                className="mb-0"
              />
              <span>
                Edited <code className="rounded bg-muted px-1 font-mono">{path}</code>
              </span>
            </button>
            {event.args?.confidence !== undefined && (
              <Badge variant={Number(event.args.confidence) >= 0.7 ? "success" : "warning"} className="text-[10px] py-0 h-5" title={`Model Confidence: ${Math.round(Number(event.args.confidence) * 100)}%`}>
                {Math.round(Number(event.args.confidence) * 100)}% Confidence
              </Badge>
            )}
          </div>
          {event.args?.old_text != null && event.args?.new_text != null && (
            <div className="mt-1.5 space-y-1 text-xs font-mono">
              <div className="rounded bg-red-500/10 p-1 text-red-600 dark:text-red-400">
                <CardCollapsibleSection
                  label="removed lines"
                  lines={oldText.split("\n").map((line) => `- ${line}`)}
                />
              </div>
              <div className="rounded bg-green-500/10 p-1 text-green-600 dark:text-green-400">
                <CardCollapsibleSection
                  label="added lines"
                  lines={newText.split("\n").map((line) => `+ ${line}`)}
                />
              </div>
            </div>
          )}
        </div>
      );

    default:
      return null;
  }
}
