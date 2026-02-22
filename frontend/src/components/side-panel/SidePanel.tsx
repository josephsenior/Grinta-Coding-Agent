import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FilesTree } from "./FilesTree";
import { GitChanges } from "./GitChanges";
import { TasksTab } from "./TasksTab";
import { PlaybooksTab } from "./PlaybooksTab";
import { Files, GitBranch, CheckSquare, BookOpen } from "lucide-react";

interface SidePanelProps {
  conversationId: string;
}

export function SidePanel({ conversationId }: SidePanelProps) {
  return (
    <Tabs defaultValue="files" className="flex h-full flex-col">
      <TabsList className="grid h-9 w-full shrink-0 grid-cols-4 rounded-none border-b bg-transparent px-0">
        <TabsTrigger
          value="files"
          className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Files"
        >
          <Files className="h-4 w-4" />
        </TabsTrigger>
        <TabsTrigger
          value="git"
          className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Git changes"
        >
          <GitBranch className="h-4 w-4" />
        </TabsTrigger>
        <TabsTrigger
          value="tasks"
          className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Tasks"
        >
          <CheckSquare className="h-4 w-4" />
        </TabsTrigger>
        <TabsTrigger
          value="playbooks"
          className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent"
          title="Playbooks"
        >
          <BookOpen className="h-4 w-4" />
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
      </div>
    </Tabs>
  );
}
