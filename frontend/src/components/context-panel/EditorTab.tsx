import Editor from "@monaco-editor/react";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";
import { Lock, Unlock } from "lucide-react";

export function EditorTab() {
  const filePath = useContextPanelStore((s) => s.editorFilePath);
  const content = useContextPanelStore((s) => s.editorContent);
  const language = useContextPanelStore((s) => s.editorLanguage);
  const readOnly = useContextPanelStore((s) => s.editorReadOnly);
  const setReadOnly = useContextPanelStore((s) => s.setEditorReadOnly);
  const theme = useAppStore((s) => s.theme);

  if (!filePath || content === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Click a file event to open it here
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-8 shrink-0 items-center justify-between border-b px-2">
        <span className="truncate text-xs font-mono text-muted-foreground">
          {filePath}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
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
