import { ActionType, ObservationType } from "@/types/agent";
import type { ForgeEvent, ActionEvent, ObservationEvent } from "@/types/events";
import { isNotifyUiOnlyErrorEvent } from "@/lib/error-observation";
import { MessageBubble } from "./MessageBubble";
import { FileCard } from "./FileCard";
import { CommandCard, CommandOutputCard } from "./CommandCard";
import { CollapsibleToolOutput } from "./CollapsibleToolOutput";
import {
  FinishCard,
  RejectCard,
  McpCard,
  LspQueryCard,
  BrowseCard,
  ClarificationCard,
  EscalateCard,
  ProposalCard,
  UncertaintyCard,
  DelegateCard,
  ErrorCard,
  McpObservationCard,
  LspObservationCard,
  BrowseObservationCard,
  DelegateResultCard,
  RecallFailureCard,
} from "./EventCards";
import { ThinkCard } from "./ThinkCard";

interface EventCardProps {
  event: ForgeEvent;
}

export function EventCard({ event }: EventCardProps) {
  // Actions
  if ("action" in event) {
    const action = event as ActionEvent;
    const renderAction = () => {
      switch (action.action) {
      case ActionType.MESSAGE:
        return <MessageBubble event={action} />;
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
      case ActionType.LSP_QUERY:
        return <LspQueryCard event={action} />;
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
      case ActionType.SUMMARIZE_CONTEXT:
        return null;

      case ActionType.THINK:
        return <ThinkCard event={action} />;

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
          <div className="rounded-md border border-border/50 bg-muted/20 px-2.5 py-1.5 text-[11px] text-muted-foreground">
            [{action.action}] {action.message}
          </div>
        );
      }
    };
    
    const node = renderAction();
    if (!node) return null;
    
    return node;
  }

  // Observations
  if ("observation" in event) {
    const obs = event as ObservationEvent;
    switch (obs.observation) {
      case ObservationType.RUN:
      case ObservationType.TERMINAL:
        return <CommandOutputCard event={obs} />;
      case ObservationType.ERROR:
        if (isNotifyUiOnlyErrorEvent(obs)) {
          return null;
        }
        return <ErrorCard event={obs} />;
      case ObservationType.MCP:
        return <McpObservationCard event={obs} />;
      case ObservationType.LSP_QUERY_RESULT:
        return <LspObservationCard event={obs} />;
      case ObservationType.BROWSE:
        return <BrowseObservationCard event={obs} />;
      case ObservationType.DELEGATE_TASK_RESULT:
        return <DelegateResultCard event={obs} />;
      case ObservationType.RECALL_FAILURE:
        return <RecallFailureCard event={obs} />;
      case ObservationType.AGENT_STATE_CHANGED:
        return null;

      // Observations that are rendered contextually or silently
      case ObservationType.READ:
      case ObservationType.WRITE:
      case ObservationType.EDIT:
        // File observation content — show if non-empty
        if (obs.content) {
          return (
            <div className="rounded-md border border-border/50 bg-muted/25 p-2.5">
              <CollapsibleToolOutput
                content={obs.content}
                previewLines={6}
                collapseWhenLines={12}
                collapseWhenChars={2500}
                preClassName="rounded border border-border/30 bg-muted/45 p-2 dark:bg-card/40"
              />
            </div>
          );
        }
        return null;

      case ObservationType.MESSAGE:
      case ObservationType.CHAT:
        if (obs.content) {
          return (
            <div className="max-w-[min(100%,42rem)] text-[13px] leading-[1.65] text-foreground">
              <p className="whitespace-pre-wrap">{obs.content}</p>
            </div>
          );
        }
        return null;

      case ObservationType.CONDENSE:
        return null;

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
          <div className="rounded-md border border-border/50 bg-muted/20 px-2.5 py-1.5 text-[11px] text-muted-foreground">
            [{obs.observation}] {obs.content || obs.message}
          </div>
        );
    }
  }

  return null;
}
