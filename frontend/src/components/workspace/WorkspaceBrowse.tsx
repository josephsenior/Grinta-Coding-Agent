import { useState, useCallback } from "react";
import { FilesTree } from "@/components/side-panel/FilesTree";
import { GitChanges } from "@/components/side-panel/GitChanges";
import { WorkspaceFilePreview } from "./WorkspaceFilePreview";
import { WorkspaceResizableChangesLayout } from "./WorkspaceResizableChangesLayout";
import { Button } from "@/components/ui/button";
import { Maximize2 } from "lucide-react";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { WORKSPACE_BROWSE_CHANGES_FRAC_KEY } from "@/hooks/use-workspace-changes-fraction";

interface WorkspaceBrowseProps {
  conversationId: string;
}

/** File tree + inline preview (split) and Changes section below. */
export function WorkspaceBrowse({ conversationId }: WorkspaceBrowseProps) {
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const openFile = useContextPanelStore((s) => s.openFile);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const handlePreviewFile = useCallback((path: string, content: string) => {
    setPreviewPath(path);
    setPreviewContent(content);
  }, []);

  const openInFullEditor = useCallback(() => {
    if (previewPath === null || previewContent === null) return;
    openFile(previewPath, previewContent);
    setContextPanelOpen(true);
  }, [previewPath, previewContent, openFile, setContextPanelOpen]);

  return (
    <WorkspaceResizableChangesLayout
      storageKey={WORKSPACE_BROWSE_CHANGES_FRAC_KEY}
      topClassName="border-b border-border/40"
      top={
        <div className="flex h-full min-h-0 overflow-hidden">
          <div className="flex w-[min(40%,260px)] shrink-0 flex-col border-r border-border/40">
            <FilesTree
              conversationId={conversationId}
              sectionTitle="Workspace"
              usePreviewPane
              onPreviewFile={handlePreviewFile}
              onPreviewLoading={setPreviewLoading}
              selectedPreviewPath={previewPath}
            />
          </div>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-muted/5">
            <div className="flex shrink-0 items-center justify-end border-b border-border/40 px-1 py-0.5">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 text-[11px] text-muted-foreground"
                disabled={!previewPath || previewContent === null}
                onClick={openInFullEditor}
                title="Open in full editor view"
              >
                <Maximize2 className="h-3 w-3" />
                Expand
              </Button>
            </div>
            <WorkspaceFilePreview
              path={previewPath}
              content={previewContent}
              loading={previewLoading}
              className="min-h-0 flex-1"
            />
          </div>
        </div>
      }
      bottom={<GitChanges conversationId={conversationId} />}
    />
  );
}
