import { useState, useEffect } from "react";
import { ChevronDown, ChevronRight, Activity, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ForgeEvent } from "@/types/events";
import { AgentState, ActionType, ObservationType } from "@/types/agent";
import { useSessionStore } from "@/stores/session-store";
import { EventCard } from "./EventRenderer";

function isVisibleEvent(event: ForgeEvent): boolean {
  if ("action" in event) {
    const silentActions = [
      ActionType.NULL,
      ActionType.STREAMING_CHUNK,
      ActionType.START,
      ActionType.SYSTEM,
      ActionType.PAUSE,
      ActionType.RESUME,
      ActionType.STOP,
      ActionType.CHANGE_AGENT_STATE,
      ActionType.PUSH,
      ActionType.SEND_PR,
      ActionType.CONDENSATION_REQUEST,
      ActionType.TASK_TRACKING,
    ];
    if (silentActions.includes(event.action as ActionType)) return false;
    return true;
  }
  if ("observation" in event) {
    const silentObservations = [
      ObservationType.NULL,
      ObservationType.STATUS,
      ObservationType.SERVER_READY,
      ObservationType.SUCCESS,
      ObservationType.TASK_TRACKING,
      ObservationType.DOWNLOAD,
      ObservationType.USER_REJECTED,
      ObservationType.THINK,
      ObservationType.RECALL,
    ];
    if (silentObservations.includes(event.observation as ObservationType)) return false;
    
    // Some observations conditionally return null in EventRenderer
    if ([ObservationType.READ, ObservationType.WRITE, ObservationType.EDIT].includes(event.observation as ObservationType)) {
      return "content" in event && !!event.content;
    }
    if ([ObservationType.MESSAGE, ObservationType.CHAT].includes(event.observation as ObservationType)) {
      return "content" in event && !!event.content;
    }
    return true;
  }
  return true;
}

interface AgentWorkflowGroupProps {
  events: ForgeEvent[];
  isLatest: boolean;
}

export function AgentWorkflowGroup({ events, isLatest }: AgentWorkflowGroupProps) {
  const agentState = useSessionStore((s) => s.agentState);
  const isRunning = agentState === AgentState.RUNNING;
  const shouldAutoExpand = isLatest && isRunning;
  
  const [isExpanded, setIsExpanded] = useState(shouldAutoExpand);

  useEffect(() => {
    if (isLatest) {
      if (isRunning) {
        setIsExpanded(true);
      } else {
        setIsExpanded(false);
      }
    }
  }, [isRunning, isLatest]);

  const visibleEvents = events.filter(isVisibleEvent);

  if (!visibleEvents || visibleEvents.length === 0) return null;

  return (
    <div className="rounded-xl border bg-card my-2 overflow-hidden shadow-sm">
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium hover:bg-muted/50 transition-colors"
      >
        <div className="flex items-center gap-2">
          {isLatest && isRunning ? (
            <Activity className="h-3.5 w-3.5 text-blue-500 animate-pulse" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          <span className={cn("text-muted-foreground font-medium", isLatest && isRunning && "text-foreground")}>
            Agent working... <span className="text-xs font-normal opacity-70 ml-1">({visibleEvents.length} step{visibleEvents.length === 1 ? '' : 's'})</span>
          </span>
        </div>
        <div className="text-muted-foreground">
          {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </div>
      </button>
      
      {isExpanded && (
        <div className="flex flex-col gap-2 p-3 border-t bg-muted/10 relative">
          <div className="absolute left-4.75 top-4 bottom-4 w-0.5 bg-border/50 rounded-full" />
          <div className="ml-6 flex flex-col gap-2">
            {visibleEvents.map((event, i) => (
              <EventCard key={event.id != null ? `wg-e-${event.id}` : `wg-i-${i}`} event={event} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
