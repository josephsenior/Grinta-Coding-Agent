import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FilesTree } from "./FilesTree";
import { GitChanges } from "./GitChanges";
import { TasksTab } from "./TasksTab";
import { PlaybooksTab } from "./PlaybooksTab";
import { ContextRadarTab } from "./ContextRadarTab";
import { Files, GitBranch, CheckSquare, BookOpen, BrainCircuit } from "lucide-react";

interface SidePanelProps {
  conversationId: string;
}

export function SidePanel({ conversationId }: SidePanelProps) {
  return (
    <Tabs defaultValue="files" className="flex h-full flex-col">
      <TabsList className="grid h-9 w-full shrink-0 grid-cols-5 rounded-none border-b bg-transparent px-0">
        <TabsTrigger
          value="files"
          className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Files"
          aria-label="Files tab"
        >
          <span className="flex flex-col items-center gap-0.5">
            <Files className="h-3.5 w-3.5" />
            <span className="text-[10px] leading-none">Files</span>
          </span>
        </TabsTrigger>
        <TabsTrigger
          value="git"
          className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Git changes"
          aria-label="Git changes tab"
        >
          <span className="flex flex-col items-center gap-0.5">
            <GitBranch className="h-3.5 w-3.5" />
            <span className="text-[10px] leading-none">Git</span>
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
          value="playbooks"
          className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Playbooks"
          aria-label="Playbooks tab"
        >
          <span className="flex flex-col items-center gap-0.5">
            <BookOpen className="h-3.5 w-3.5" />
            <span className="text-[10px] leading-none">Playbooks</span>
          </span>
        </TabsTrigger>
        <TabsTrigger
          value="radar"
          className="h-full rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Context Radar"
          aria-label="Context radar tab"
        >
          <span className="flex flex-col items-center gap-0.5">
            <BrainCircuit className="h-3.5 w-3.5" />
            <span className="text-[10px] leading-none">Radar</span>
          </span>
        </TabsTrigger>
      </TabsList>

      <div className="min-h-0 flex-1">
        <TabsContent value="files" className="m-0 h-full data-[state=inactive]:hidden">
          <FilesTree conversationId={conversationId} />
        </TabsContent>
        <TabsContent value="git" className="m-0 h-full data-[state=inactive]:hidden">
          <GitChanges conversationId={conversationId} />
        </TabsContent>
        <TabsContent value="tasks" className="m-0 h-full data-[state=inactive]:hidden">
          <TasksTab />
        </TabsContent>
        <TabsContent value="playbooks" className="m-0 h-full data-[state=inactive]:hidden">
          <PlaybooksTab conversationId={conversationId} />
        </TabsContent>
        <TabsContent value="radar" className="m-0 h-full data-[state=inactive]:hidden">
          <ContextRadarTab />
        </TabsContent>
      </div>
    </Tabs>
  );
}
