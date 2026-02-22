import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useContextPanelStore, type ContextTab } from "@/stores/context-panel-store";
import { EditorTab } from "./EditorTab";
import { TerminalTab } from "./TerminalTab";
import { DiffTab } from "./DiffTab";
import { PreviewTab } from "./PreviewTab";
import { FileCode, TerminalSquare, GitCompare, Eye } from "lucide-react";

export function ContextPanel() {
  const activeTab = useContextPanelStore((s) => s.activeTab);
  const setActiveTab = useContextPanelStore((s) => s.setActiveTab);

  return (
    <div className="flex h-full flex-col">
      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as ContextTab)}
        className="flex h-full flex-col"
      >
        <TabsList className="mx-2 mt-1 h-8 shrink-0">
          <TabsTrigger value="editor" className="gap-1 text-xs px-2 py-1">
            <FileCode className="h-3 w-3" />
            Editor
          </TabsTrigger>
          <TabsTrigger value="terminal" className="gap-1 text-xs px-2 py-1">
            <TerminalSquare className="h-3 w-3" />
            Terminal
          </TabsTrigger>
          <TabsTrigger value="diff" className="gap-1 text-xs px-2 py-1">
            <GitCompare className="h-3 w-3" />
            Diff
          </TabsTrigger>
          <TabsTrigger value="preview" className="gap-1 text-xs px-2 py-1">
            <Eye className="h-3 w-3" />
            Preview
          </TabsTrigger>
        </TabsList>

        <TabsContent value="editor" className="flex-1 overflow-hidden">
          <EditorTab />
        </TabsContent>
        <TabsContent value="terminal" className="flex-1 overflow-hidden">
          <TerminalTab />
        </TabsContent>
        <TabsContent value="diff" className="flex-1 overflow-hidden">
          <DiffTab />
        </TabsContent>
        <TabsContent value="preview" className="flex-1 overflow-hidden">
          <PreviewTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
