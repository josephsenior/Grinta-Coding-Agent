import { useState, useEffect, useCallback } from "react";
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

function buildTree(paths: string[]): FileNode[] {
  const root: FileNode[] = [];

  for (const p of paths) {
    const normalized = p.replace(/\\/g, "/");
    const parts = normalized.split("/").filter(Boolean);

    let currentLevel = root;
    let currentPath = "";

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i] ?? "";
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      const isLast = i === parts.length - 1;

      let node: FileNode | undefined = currentLevel.find((n) => n.name === part);
      if (!node) {
        node = {
          name: part,
          path: currentPath,
          isDir: !isLast,
          children: !isLast ? [] : undefined,
        };
        currentLevel.push(node);
      }
      if (!isLast && node.children) {
        currentLevel = node.children;
      }
    }
  }

  return root;
}

interface TreeNodeProps {
  node: FileNode;
  depth: number;
  conversationId: string;
}

function TreeNode({ node, depth, conversationId }: TreeNodeProps) {
  const [open, setOpen] = useState(false);
  const openFile = useContextPanelStore((s) => s.openFile);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const handleClick = async () => {
    if (node.isDir) {
      setOpen((v) => !v);
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

  return (
    <div>
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "flex w-full items-center gap-1.5 rounded px-2 py-1 text-xs hover:bg-accent transition-colors text-left",
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
            <TreeNode key={child.path} node={child} depth={depth + 1} conversationId={conversationId} />
          ))}
        </div>
      )}
    </div>
  );
}

interface FilesTreeProps {
  conversationId: string;
}

export function FilesTree({ conversationId }: FilesTreeProps) {
  const [files, setFiles] = useState<FileNode[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!conversationId) return;
    setLoading(true);
    try {
      const paths = await listFiles(conversationId);
      setFiles(buildTree(paths));
    } catch {
      toast.error("Could not load files");
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Files
        </span>
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
          ) : files.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted-foreground">No files found</p>
          ) : (
            files.map((node) => (
              <TreeNode key={node.path} node={node} depth={0} conversationId={conversationId} />
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
