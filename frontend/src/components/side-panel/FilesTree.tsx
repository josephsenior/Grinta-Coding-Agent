import { useState, useEffect, useCallback } from "react";
import { useRefetchWhenBackendRecovers } from "@/hooks/use-refetch-when-backend-recovers";
import { Folder, FolderOpen, FileText, Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { listFiles, getFileContent } from "@/api/files";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface FileNode {
  name: string;
  path: string;
  isDir: boolean;
  children?: FileNode[];
}

/**
 * Build a tree from flat paths. Paths ending with `/` are directories (API convention);
 * a single segment like `downloads/` must stay a folder after split (trailing slash is lost on split).
 */
function buildTree(paths: string[]): FileNode[] {
  const root: FileNode[] = [];

  for (const p of paths) {
    const normalized = p.replace(/\\/g, "/");
    const isTrailingDir = normalized.endsWith("/");
    const trimmed = normalized.replace(/\/+$/, "");
    if (!trimmed) continue;
    const parts = trimmed.split("/").filter(Boolean);

    let currentLevel = root;
    let currentPath = "";

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i] ?? "";
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      const isLast = i === parts.length - 1;
      const segmentIsDir = !isLast || isTrailingDir;

      let node = currentLevel.find((n) => n.name === part);
      if (!node) {
        node = {
          name: part,
          path: currentPath,
          isDir: segmentIsDir,
          children: segmentIsDir ? [] : undefined,
        };
        currentLevel.push(node);
      } else if (segmentIsDir && !node.isDir) {
        node.isDir = true;
        node.children = node.children ?? [];
      }

      if (!segmentIsDir) break;
      if (!node.children) node.children = [];
      currentLevel = node.children;
    }
  }

  const sortLevel = (nodes: FileNode[]) => {
    nodes.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    });
    for (const n of nodes) {
      if (n.children?.length) sortLevel(n.children);
    }
  };
  sortLevel(root);
  return root;
}

interface TreeNodeProps {
  node: FileNode;
  depth: number;
  conversationId: string;
  selectedPath: string | null;
  usePreviewPane: boolean;
  onPreviewFile?: (path: string, content: string) => void;
  onPreviewLoading?: (loading: boolean) => void;
}

function TreeNode({
  node,
  depth,
  conversationId,
  selectedPath,
  usePreviewPane,
  onPreviewFile,
  onPreviewLoading,
}: TreeNodeProps) {
  const [open, setOpen] = useState(false);
  const openFile = useContextPanelStore((s) => s.openFile);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const handleClick = async () => {
    if (node.isDir) {
      setOpen((v) => !v);
      return;
    }
    if (usePreviewPane && onPreviewFile) {
      onPreviewLoading?.(true);
      try {
        const content = await getFileContent(conversationId, node.path);
        onPreviewFile(node.path, content);
      } catch {
        toast.error("Could not load file");
      } finally {
        onPreviewLoading?.(false);
      }
      return;
    }
    try {
      const content = await getFileContent(conversationId, node.path);
      openFile(node.path, content);
      setContextPanelOpen(true);
    } catch {
      toast.error("Could not load file");
    }
  };

  const isSelected = !node.isDir && selectedPath === node.path;

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "flex w-full items-center gap-1.5 rounded px-2 py-1 text-xs transition-colors text-left hover:bg-accent",
          isSelected && "bg-accent/60",
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {node.isDir ? (
          open ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-yellow-500" />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-yellow-500" />
          )
        ) : (
          <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate">{node.name}</span>
      </button>
      {node.isDir && open && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              conversationId={conversationId}
              selectedPath={selectedPath}
              usePreviewPane={usePreviewPane}
              onPreviewFile={onPreviewFile}
              onPreviewLoading={onPreviewLoading}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export interface FilesTreeProps {
  conversationId: string;
  /** Column header label (default &quot;Files&quot;). */
  sectionTitle?: string;
  /**
   * When true, loads a recursive file list and clicking a file does not switch workspace view;
   * use with onPreviewFile for split-pane preview.
   */
  usePreviewPane?: boolean;
  onPreviewFile?: (path: string, content: string) => void;
  onPreviewLoading?: (loading: boolean) => void;
  selectedPreviewPath?: string | null;
}

export function FilesTree({
  conversationId,
  sectionTitle = "Files",
  usePreviewPane = false,
  onPreviewFile,
  onPreviewLoading,
  selectedPreviewPath = null,
}: FilesTreeProps) {
  const [files, setFiles] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!conversationId) return;
    setLoading(true);
    setLoadError(false);
    try {
      const paths = await listFiles(conversationId, undefined, {
        recursive: usePreviewPane,
      });
      setFiles(buildTree(paths));
    } catch {
      setLoadError(true);
      setFiles([]);
      if (!opts?.silent) {
        toast.error("Could not load files", {
          description: "Check that the Forge backend is running, then use Refresh.",
        });
      }
    } finally {
      setLoading(false);
    }
  }, [conversationId, usePreviewPane]);

  useEffect(() => {
    load();
  }, [load]);

  useRefetchWhenBackendRecovers(() => load({ silent: true }), true, loadError);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {sectionTitle}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={() => void load()}
          title="Refresh"
        >
          <RefreshCw className="h-3 w-3" />
        </Button>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="p-1">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : loadError ? (
            <div className="space-y-2 px-3 py-4">
              <p className="text-xs font-medium text-destructive">Couldn&apos;t load the file list</p>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Confirm the API is up and this conversation has a workspace. Press{" "}
                <span className="font-medium text-foreground/80">Refresh</span> in the header to try again.
              </p>
            </div>
          ) : files.length === 0 ? (
            <div className="space-y-1.5 px-3 py-4">
              <p className="text-xs text-muted-foreground">No files in the workspace yet.</p>
              <p className="text-[11px] leading-relaxed text-muted-foreground/90">
                After the agent creates or edits files for this chat, they will show up here. You can also
                use Refresh if you expect files already.
              </p>
            </div>
          ) : (
            files.map((node) => (
              <TreeNode
                key={node.path}
                node={node}
                depth={0}
                conversationId={conversationId}
                selectedPath={selectedPreviewPath}
                usePreviewPane={Boolean(usePreviewPane && onPreviewFile)}
                onPreviewFile={onPreviewFile}
                onPreviewLoading={onPreviewLoading}
              />
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
