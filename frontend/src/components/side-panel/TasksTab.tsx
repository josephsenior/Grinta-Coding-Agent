import { CheckSquare, Clock, CheckCircle2, XCircle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { useSessionStore } from "@/stores/session-store";
import { ActionType } from "@/types/agent";
import type { ActionEvent } from "@/types/events";
import { cn } from "@/lib/utils";

type TaskStatus = "open" | "in_progress" | "completed" | "abandoned";

interface Task {
  id: string;
  goal: string;
  status: TaskStatus;
  subtasks?: Task[];
}

function statusIcon(status: TaskStatus) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-500" />;
    case "abandoned":
      return <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />;
    case "in_progress":
      return <Clock className="h-3.5 w-3.5 shrink-0 text-blue-500 animate-pulse" />;
    default:
      return <CheckSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />;
  }
}

function statusVariant(status: TaskStatus): "default" | "secondary" | "success" | "destructive" {
  switch (status) {
    case "completed":
      return "success";
    case "abandoned":
      return "destructive";
    case "in_progress":
      return "default";
    default:
      return "secondary";
  }
}

function TaskRow({ task, depth = 0 }: { task: Task; depth?: number }) {
  return (
    <div>
      <div
        className="flex items-start gap-2 rounded px-2 py-1.5 hover:bg-accent transition-colors"
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {statusIcon(task.status)}
        <span
          className={cn(
            "flex-1 text-xs",
            task.status === "completed" && "line-through text-muted-foreground",
            task.status === "abandoned" && "line-through opacity-50",
          )}
        >
          {task.goal}
        </span>
        <Badge variant={statusVariant(task.status)} className="h-4 shrink-0 px-1 text-[10px]">
          {task.status.replace("_", " ")}
        </Badge>
      </div>
      {task.subtasks?.map((sub) => (
        <TaskRow key={sub.id} task={sub} depth={depth + 1} />
      ))}
    </div>
  );
}

export function TasksTab() {
  const events = useSessionStore((s) => s.events);

  // Extract all TASK_TRACKING action events and take the latest snapshot
  const taskEvents = events.filter(
    (e): e is ActionEvent => "action" in e && e.action === ActionType.TASK_TRACKING,
  );

  // The latest TASK_TRACKING event should contain the full task tree
  const latestTaskEvent = taskEvents[taskEvents.length - 1];
  const tasks: Task[] = latestTaskEvent
    ? (latestTaskEvent.args?.tasks as Task[] | undefined) ?? []
    : [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <CheckSquare className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Tasks
        </span>
        {tasks.length > 0 && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
            {tasks.length}
          </Badge>
        )}
      </div>
      <ScrollArea className="flex-1">
        <div className="p-1">
          {tasks.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              Sub-task queue empty
            </p>
          ) : (
            tasks.map((task) => <TaskRow key={task.id} task={task} />)
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
