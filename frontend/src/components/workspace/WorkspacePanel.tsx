import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useContextPanelStore } from "@/stores/context-panel-store";
import { EditorTab } from "@/components/context-panel/EditorTab";
import { DiffTab } from "@/components/context-panel/DiffTab";
import { WorkspaceBrowse } from "./WorkspaceBrowse";
import { TasksTab } from "@/components/side-panel/TasksTab";
import { SkillsTab } from "@/components/side-panel/SkillsTab";
import { TerminalTab } from "@/components/context-panel/TerminalTab";
import { PanelsTopLeft, CheckSquare, Sparkles, SquareTerminal } from "lucide-react";

interface WorkspacePanelProps {
  conversationId: string;
}

export function WorkspacePanel({ conversationId }: WorkspacePanelProps) {
  const workspaceView = useContextPanelStore((s) => s.workspaceView);

  return (
    <div className="flex h-full min-h-0 flex-col bg-transparent">
      {workspaceView === "browse" && (
        <Tabs defaultValue="workspace" className="flex h-full min-h-0 flex-col">
          <TabsList className="grid h-9 w-full shrink-0 grid-cols-4 rounded-none border-b bg-transparent px-0">
            <TabsTrigger
              value="workspace"
              className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
              title="Files, preview, and git changes"
              aria-label="Workspace tab"
            >
              <span className="flex flex-col items-center gap-0.5">
                <PanelsTopLeft className="h-3.5 w-3.5" />
                <span className="text-[10px] leading-none">Workspace</span>
              </span>
            </TabsTrigger>
            <TabsTrigger
              value="tasks"
              className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
              title="Tasks"
              aria-label="Tasks tab"
            >
              <span className="flex flex-col items-center gap-0.5">
                <CheckSquare className="h-3.5 w-3.5" />
                <span className="text-[10px] leading-none">Tasks</span>
              </span>
            </TabsTrigger>
            <TabsTrigger
              value="skills"
              className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
              title="Skills — workspace playbooks and custom prompts"
              aria-label="Skills tab"
            >
              <span className="flex flex-col items-center gap-0.5">
                <Sparkles className="h-3.5 w-3.5" />
                <span className="text-[10px] leading-none">Skills</span>
              </span>
            </TabsTrigger>
            <TabsTrigger
              value="terminal"
              className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
              title="Live terminal output"
              aria-label="Terminal tab"
            >
              <span className="flex flex-col items-center gap-0.5">
                <SquareTerminal className="h-3.5 w-3.5" />
                <span className="text-[10px] leading-none">Terminal</span>
              </span>
            </TabsTrigger>
          </TabsList>

          <div className="min-h-0 flex-1">
            <TabsContent value="workspace" className="m-0 h-full data-[state=inactive]:hidden">
              <WorkspaceBrowse conversationId={conversationId} />
            </TabsContent>
            <TabsContent value="tasks" className="m-0 h-full data-[state=inactive]:hidden">
              <TasksTab />
            </TabsContent>
            <TabsContent value="skills" className="m-0 h-full data-[state=inactive]:hidden">
              <SkillsTab conversationId={conversationId} />
            </TabsContent>
            <TabsContent value="terminal" className="m-0 h-full data-[state=inactive]:hidden">
              <TerminalTab />
            </TabsContent>
          </div>
        </Tabs>
      )}
      {workspaceView === "editor" && <EditorTab />}
      {workspaceView === "diff" && <DiffTab />}
    </div>
  );
}
