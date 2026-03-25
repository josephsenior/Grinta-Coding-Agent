import { ActionType, ObservationType } from "@/types/agent";
import type { ActionEvent, ForgeEvent, ObservationEvent } from "@/types/events";

export interface TimelineStepStats {
  fileOps: number;
  commands: number;
  toolCalls: number;
}

export interface TimelineStep {
  id: string;
  title: string;
  summary: string;
  status: "running" | "done" | "needs_attention";
  events: ForgeEvent[];
  stats: TimelineStepStats;
}

function isUserMessageAction(event: ForgeEvent): event is ActionEvent {
  return (
    "action" in event &&
    event.action === ActionType.MESSAGE &&
    event.source === "user"
  );
}

function truncate(text: string, max: number): string {
  const trimmed = text.trim();
  if (trimmed.length <= max) return trimmed;
  return `${trimmed.slice(0, max - 1)}…`;
}

function extractUserPromptText(event: ActionEvent): string {
  const message = String(event.message || event.args?.content || "").trim();
  return message || "Prompt";
}

function buildStepStats(events: ForgeEvent[]): TimelineStepStats {
  let fileOps = 0;
  let commands = 0;
  let toolCalls = 0;

  for (const event of events) {
    if (!("action" in event)) continue;
    const action = event.action;
    if (action === ActionType.READ || action === ActionType.WRITE || action === ActionType.EDIT) {
      fileOps += 1;
      continue;
    }
    if (action === ActionType.RUN || action === ActionType.TERMINAL_RUN || action === ActionType.TERMINAL_INPUT) {
      commands += 1;
      continue;
    }
    if (
      action === ActionType.MCP ||
      action === ActionType.BROWSE ||
      action === ActionType.BROWSE_INTERACTIVE ||
      action === ActionType.DELEGATE_TASK
    ) {
      toolCalls += 1;
    }
  }

  return { fileOps, commands, toolCalls };
}

function summarizeStep(events: ForgeEvent[]): Pick<TimelineStep, "summary" | "status"> {
  const reversed = [...events].reverse();

  for (const event of reversed) {
    if ("observation" in event) {
      const obs = event as ObservationEvent;
      if (obs.observation === ObservationType.ERROR || obs.observation === ObservationType.RECALL_FAILURE) {
        return { summary: "Hit an issue and needs attention", status: "needs_attention" };
      }
      if (obs.observation === ObservationType.AGENT_STATE_CHANGED) {
        const state = String(obs.extras?.agent_state ?? "");
        if (state === "awaiting_user_confirmation") {
          return { summary: "Waiting for your approval", status: "needs_attention" };
        }
        if (state === "awaiting_user_input" || state === "finished") {
          return { summary: "Completed this step", status: "done" };
        }
      }
    }

    if ("action" in event) {
      const action = event as ActionEvent;
      if (action.source === "agent" && action.action === ActionType.MESSAGE) {
        return { summary: "Replied with a result", status: "done" };
      }
      if (action.action === ActionType.THINK) {
        return { summary: "Reasoning through the task", status: "running" };
      }
      if (action.action === ActionType.MCP || action.action === ActionType.BROWSE || action.action === ActionType.BROWSE_INTERACTIVE) {
        return { summary: "Using tools to gather/verify information", status: "running" };
      }
      if (action.action === ActionType.RUN || action.action === ActionType.TERMINAL_RUN) {
        return { summary: "Running commands and validating output", status: "running" };
      }
      if (action.action === ActionType.READ || action.action === ActionType.WRITE || action.action === ActionType.EDIT) {
        return { summary: "Inspecting and updating project files", status: "running" };
      }
    }
  }

  return { summary: "Working on this step", status: "running" };
}

export function buildTimelineSteps(events: ForgeEvent[]): TimelineStep[] {
  if (events.length === 0) return [];

  const ordered = [...events].sort((a, b) => Number(a.id) - Number(b.id));
  const buckets: { title: string; events: ForgeEvent[] }[] = [];

  let current: { title: string; events: ForgeEvent[] } | null = null;
  let stepIndex = 0;

  for (const event of ordered) {
    if (isUserMessageAction(event)) {
      if (current && current.events.length > 0) {
        buckets.push(current);
      }
      stepIndex += 1;
      current = {
        title: `Step ${stepIndex}: ${truncate(extractUserPromptText(event), 72)}`,
        events: [event],
      };
      continue;
    }

    if (!current) {
      current = { title: "Session setup", events: [] };
    }
    current.events.push(event);
  }

  if (current && current.events.length > 0) {
    buckets.push(current);
  }

  return buckets.map((bucket, idx) => {
    const { summary, status } = summarizeStep(bucket.events);
    return {
      id: `step-${idx + 1}-${Number(bucket.events[0]?.id ?? idx)}`,
      title: bucket.title,
      summary,
      status,
      events: bucket.events,
      stats: buildStepStats(bucket.events),
    };
  });
}
