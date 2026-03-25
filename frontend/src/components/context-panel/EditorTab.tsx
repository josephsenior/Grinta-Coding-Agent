import Editor from "@monaco-editor/react";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Lock, Unlock } from "lucide-react";

export function EditorTab() {
  const filePath = useContextPanelStore((s) => s.editorFilePath);
  const content = useContextPanelStore((s) => s.editorContent);
  const language = useContextPanelStore((s) => s.editorLanguage);
  const readOnly = useContextPanelStore((s) => s.editorReadOnly);
  const setReadOnly = useContextPanelStore((s) => s.setEditorReadOnly);
  const goToBrowse = useContextPanelStore((s) => s.goToBrowse);
  const theme = useAppStore((s) => s.theme);

  if (!filePath || content === null) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex h-8 shrink-0 items-center border-b px-1">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs text-muted-foreground"
            onClick={() => goToBrowse()}
          >
            <ArrowLeft className="h-3 w-3" />
            Workspace
          </Button>
        </div>
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          Open a file from the tree or a chat card
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 shrink-0 items-center gap-1 border-b px-1">
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0 text-muted-foreground"
          onClick={() => goToBrowse()}
          title="Back to workspace"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </Button>
        <span className="min-w-0 flex-1 truncate text-xs font-mono text-muted-foreground">
          {filePath}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0"
          onClick={() => setReadOnly(!readOnly)}
          title={readOnly ? "Switch to edit mode" : "Switch to read-only"}
        >
          {readOnly ? <Lock className="h-3 w-3" /> : <Unlock className="h-3 w-3" />}
        </Button>
      </div>
      <div className="flex-1">
        <Editor
          height="100%"
          language={language}
          value={content}
          theme={theme === "dark" ? "vs-dark" : "vs"}
          options={{
            readOnly,
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
