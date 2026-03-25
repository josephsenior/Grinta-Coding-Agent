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
import { ideToolShell, ideCaption } from "./chat-ide-styles";
import { cn } from "@/lib/utils";

interface FileCardProps {
  event: ActionEvent;
}

function lineCount(text: string): number {
  if (!text.trim()) return 0;
  return text.split("\n").length;
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
          className={cn(ideToolShell, "w-full transition-colors hover:bg-muted/40")}
        >
          <div className={cn(ideCaption, "mb-0.5 flex items-center gap-1.5")}>
            <FileText className="h-3 w-3 opacity-50" />
            <span>Read</span>
          </div>
          <code className="block break-all font-mono text-[11px] text-foreground/90">
            {path}
            {lineRange}
          </code>
        </button>
      );

    case ActionType.WRITE:
      return (
        <button
          type="button"
          onClick={handleOpenFile}
          className={cn(ideToolShell, "w-full transition-colors hover:bg-muted/40")}
        >
          <div className={cn(ideCaption, "mb-0.5 flex items-center gap-1.5")}>
            <FilePlus className="h-3 w-3 opacity-50" />
            <span>Created</span>
          </div>
          <code className="block break-all font-mono text-[11px] text-foreground/90">{path}</code>
        </button>
      );

    case ActionType.EDIT:
      return (
        <div className={cn(ideToolShell, "p-2.5")}>
          <div className="flex w-full items-start justify-between gap-2">
            <button
              type="button"
              onClick={handleOpenDiff}
              className="min-w-0 flex-1 text-left transition-opacity hover:opacity-90"
            >
              <div className={cn(ideCaption, "mb-0.5 flex flex-wrap items-center gap-1.5")}>
                <Pencil className="h-3 w-3 opacity-50" />
                <span>Edited</span>
                {oldText && newText && (
                  <>
                    {lineCount(newText) > 0 && (
                      <span className="tabular-nums text-emerald-600 dark:text-emerald-400">
                        +{lineCount(newText)}
                      </span>
                    )}
                    {lineCount(oldText) > 0 && (
                      <span className="tabular-nums text-red-500 dark:text-red-400">
                        −{lineCount(oldText)}
                      </span>
                    )}
                  </>
                )}
              </div>
              <code className="block break-all font-mono text-[11px] text-foreground/90">{path}</code>
            </button>
            {event.args?.confidence !== undefined && (
              <Badge
                variant={Number(event.args.confidence) >= 0.7 ? "secondary" : "outline"}
                className="h-5 shrink-0 px-1.5 text-[10px] font-normal"
                title={`Confidence ${Math.round(Number(event.args.confidence) * 100)}%`}
              >
                {Math.round(Number(event.args.confidence) * 100)}%
              </Badge>
            )}
          </div>
          {event.args?.old_text != null && event.args?.new_text != null && (
            <div className="mt-2 space-y-1.5 font-mono text-[11px]">
              <div className="rounded border border-border/40 bg-red-500/5 p-2 text-red-700/90 dark:text-red-400/85">
                <CardCollapsibleSection
                  label="Removed"
                  lines={oldText.split("\n").map((line) => `- ${line}`)}
                />
              </div>
              <div className="rounded border border-border/40 bg-emerald-500/5 p-2 text-emerald-800/90 dark:text-emerald-400/80">
                <CardCollapsibleSection
                  label="Added"
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
