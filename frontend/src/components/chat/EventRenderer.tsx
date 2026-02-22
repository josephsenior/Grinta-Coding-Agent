import { ActionType, ObservationType } from "@/types/agent";
import type { ForgeEvent, ActionEvent, ObservationEvent } from "@/types/events";
import { MessageBubble } from "./MessageBubble";
import { ThinkCard } from "./ThinkCard";
import { FileCard } from "./FileCard";
import { CommandCard, CommandOutputCard } from "./CommandCard";
import {
  FinishCard,
  RejectCard,
  McpCard,
  BrowseCard,
  ClarificationCard,
  EscalateCard,
  ProposalCard,
  UncertaintyCard,
  DelegateCard,
  CondensationCard,
  ErrorCard,
  McpObservationCard,
  BrowseObservationCard,
  DelegateResultCard,
  RecallFailureCard,
  AgentStateChangedPill,
} from "./EventCards";

interface EventCardProps {
  event: ForgeEvent;
}

export function EventCard({ event }: EventCardProps) {
  // Actions
  if ("action" in event) {
    const action = event as ActionEvent;
    switch (action.action) {
      case ActionType.MESSAGE:
        return <MessageBubble event={action} />;
      case ActionType.THINK:
        return <ThinkCard event={action} />;
      case ActionType.READ:
      case ActionType.WRITE:
      case ActionType.EDIT:
        return <FileCard event={action} />;
      case ActionType.RUN:
        return <CommandCard event={action} />;
      case ActionType.TERMINAL_RUN:
      case ActionType.TERMINAL_INPUT:
        return <CommandCard event={action} />;
      case ActionType.FINISH:
        return <FinishCard event={action} />;
      case ActionType.REJECT:
        return <RejectCard event={action} />;
      case ActionType.MCP:
        return <McpCard event={action} />;
      case ActionType.BROWSE:
      case ActionType.BROWSE_INTERACTIVE:
        return <BrowseCard event={action} />;
      case ActionType.CLARIFICATION:
        return <ClarificationCard event={action} />;
      case ActionType.ESCALATE:
        return <EscalateCard event={action} />;
      case ActionType.PROPOSAL:
        return <ProposalCard event={action} />;
      case ActionType.UNCERTAINTY:
        return <UncertaintyCard event={action} />;
      case ActionType.DELEGATE_TASK:
        return <DelegateCard event={action} />;
      case ActionType.RECALL:
      case ActionType.CONDENSATION:
        return <CondensationCard event={action} />;

      // Silent / internal actions
      case ActionType.NULL:
      case ActionType.STREAMING_CHUNK:
      case ActionType.START:
      case ActionType.SYSTEM:
      case ActionType.PAUSE:
      case ActionType.RESUME:
      case ActionType.STOP:
      case ActionType.CHANGE_AGENT_STATE:
      case ActionType.PUSH:
      case ActionType.SEND_PR:
      case ActionType.CONDENSATION_REQUEST:
      case ActionType.TASK_TRACKING:
        return null;

      default:
        // Fallback for unhandled action types
        if (!action.message) return null;
        return (
          <div className="rounded-lg border p-2 text-xs text-muted-foreground">
            [{action.action}] {action.message}
          </div>
        );
    }
  }

  // Observations
  if ("observation" in event) {
    const obs = event as ObservationEvent;
    switch (obs.observation) {
      case ObservationType.RUN:
      case ObservationType.TERMINAL:
        return <CommandOutputCard event={obs} />;
      case ObservationType.ERROR:
        return <ErrorCard event={obs} />;
      case ObservationType.MCP:
        return <McpObservationCard event={obs} />;
      case ObservationType.BROWSE:
        return <BrowseObservationCard event={obs} />;
      case ObservationType.DELEGATE_TASK_RESULT:
        return <DelegateResultCard event={obs} />;
      case ObservationType.RECALL_FAILURE:
        return <RecallFailureCard event={obs} />;
      case ObservationType.AGENT_STATE_CHANGED:
        return <AgentStateChangedPill event={obs} />;

      // Observations that are rendered contextually or silently
      case ObservationType.READ:
      case ObservationType.WRITE:
      case ObservationType.EDIT:
        // File observation content — show if non-empty
        if (obs.content) {
          return (
            <div className="rounded-lg border bg-zinc-950 p-3 text-xs">
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-zinc-300">
                {obs.content.length > 2000
                  ? obs.content.slice(0, 2000) + "\n..."
                  : obs.content}
              </pre>
            </div>
          );
        }
        return null;

      case ObservationType.MESSAGE:
      case ObservationType.CHAT:
        if (obs.content) {
          return (
            <div className="max-w-[80%] rounded-lg bg-muted p-3 text-sm">
              <p className="whitespace-pre-wrap">{obs.content}</p>
            </div>
          );
        }
        return null;

      case ObservationType.CONDENSE:
        return (
          <div className="flex justify-center py-1">
            <span className="rounded-full bg-muted px-3 py-0.5 text-[11px] text-muted-foreground">
              Context condensed
            </span>
          </div>
        );

      case ObservationType.NULL:
      case ObservationType.STATUS:
      case ObservationType.SERVER_READY:
      case ObservationType.SUCCESS:
      case ObservationType.TASK_TRACKING:
      case ObservationType.DOWNLOAD:
      case ObservationType.USER_REJECTED:
      case ObservationType.THINK:
      case ObservationType.RECALL:
        return null;

      default:
        if (!obs.content && !obs.message) return null;
        return (
          <div className="rounded-lg border p-2 text-xs text-muted-foreground">
            [{obs.observation}] {obs.content || obs.message}
          </div>
        );
    }
  }

  return null;
}
