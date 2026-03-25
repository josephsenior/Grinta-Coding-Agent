import Editor from "@monaco-editor/react";
import { Loader2 } from "lucide-react";
import { useAppStore } from "@/stores/app-store";
import { inferMonacoLanguage } from "@/lib/monaco-language";
import { cn } from "@/lib/utils";

interface WorkspaceFilePreviewProps {
  path: string | null;
  content: string | null;
  loading: boolean;
  className?: string;
}

/** Read-only Monaco preview for the workspace split pane. */
export function WorkspaceFilePreview({
  path,
  content,
  loading,
  className,
}: WorkspaceFilePreviewProps) {
  const theme = useAppStore((s) => s.theme);

  if (loading) {
    return (
      <div
        className={cn(
          "flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground",
          className,
        )}
      >
        <Loader2 className="h-5 w-5 animate-spin opacity-70" />
        <span className="text-xs">Loading file…</span>
      </div>
    );
  }

  if (!path || content === null) {
    return (
      <div
        className={cn(
          "flex flex-1 items-center justify-center px-4 text-center text-xs text-muted-foreground",
          className,
        )}
      >
        Select a file in the tree on the left to preview it here. If the list is empty, wait for the agent
        to add files or use Refresh on the workspace header.
      </div>
    );
  }

  return (
    <div className={cn("flex min-h-0 flex-1 flex-col overflow-hidden", className)}>
      <div className="shrink-0 border-b border-border/40 px-2 py-1.5">
        <span className="block truncate font-mono text-[11px] text-muted-foreground">
          {path}
        </span>
      </div>
      <div className="min-h-0 flex-1">
        <Editor
          height="100%"
          language={inferMonacoLanguage(path)}
          value={content}
          theme={theme === "dark" ? "vs-dark" : "vs"}
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 12,
            lineNumbers: "on",
            scrollBeyondLastLine: false,
            wordWrap: "on",
            bracketPairColorization: { enabled: true },
            automaticLayout: true,
          }}
        />
      </div>
    </div>
  );
}
