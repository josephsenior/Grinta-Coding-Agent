import type { LucideIcon } from "lucide-react";
import {
  Brain,
  FilePlus,
  FileText,
  ListOrdered,
  Loader2,
  MessageSquare,
  Pencil,
  Search,
  Sparkles,
  Terminal,
  Wrench,
  ArrowRightLeft,
  HelpCircle,
} from "lucide-react";
import { ActionType } from "@/types/agent";
import type { ForgeEvent, ActionEvent } from "@/types/events";

export interface LiveActivity {
  Icon: LucideIcon;
  verb: string;
  detail?: string;
  linesAdded?: number;
  linesRemoved?: number;
}

const SILENT_ACTIONS = new Set<ActionType>([
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
  ActionType.RECALL,
  ActionType.CONDENSATION,
  ActionType.SUMMARIZE_CONTEXT,
]);

function lineCount(text: string): number {
  if (!text.trim()) return 0;
  return text.split("\n").length;
}

function editLineStats(action: ActionEvent): { added: number; removed: number } | null {
  if (action.action !== ActionType.EDIT) return null;
  const oldT = action.args?.old_text != null ? String(action.args.old_text) : "";
  const newT = action.args?.new_text != null ? String(action.args.new_text) : "";
  if (!oldT && !newT) return null;
  return { removed: lineCount(oldT), added: lineCount(newT) };
}

function actionActivity(action: ActionEvent): LiveActivity | null {
  const path = String(action.args?.path ?? "");
  const cmd = String(action.args?.command ?? "").trim();
  const url = String(action.args?.url ?? "").trim();
  const tool = String(action.args?.tool_name ?? "tool");

  switch (action.action) {
    case ActionType.THINK:
      return { Icon: Brain, verb: "Thinking" };
    case ActionType.READ:
      return { Icon: FileText, verb: "Read", detail: path || undefined };
    case ActionType.WRITE:
      return { Icon: FilePlus, verb: "Created", detail: path || undefined };
    case ActionType.EDIT: {
      const stats = editLineStats(action);
      return {
        Icon: Pencil,
        verb: "Edited",
        detail: path || undefined,
        linesAdded: stats?.added,
        linesRemoved: stats?.removed,
      };
    }
    case ActionType.RUN:
    case ActionType.TERMINAL_RUN:
    case ActionType.TERMINAL_INPUT:
      return {
        Icon: Terminal,
        verb: "Ran",
        detail: cmd ? (cmd.length > 48 ? `${cmd.slice(0, 48)}…` : cmd) : undefined,
      };
    case ActionType.BROWSE:
    case ActionType.BROWSE_INTERACTIVE:
      return {
        Icon: Search,
        verb: action.action === ActionType.BROWSE_INTERACTIVE ? "Browsing" : "Searched web",
        detail: url ? (url.length > 40 ? `${url.slice(0, 40)}…` : url) : undefined,
      };
    case ActionType.MCP:
      return { Icon: Wrench, verb: "Using tool", detail: tool };
    case ActionType.DELEGATE_TASK:
      return {
        Icon: ArrowRightLeft,
        verb: "Delegated",
        detail: action.message || String(action.args?.task ?? "") || undefined,
      };
    case ActionType.PROPOSAL:
      return { Icon: ListOrdered, verb: "Planning", detail: "Choosing next step" };
    case ActionType.UNCERTAINTY:
      return { Icon: HelpCircle, verb: "Reviewing", detail: "Checking confidence" };
    case ActionType.CLARIFICATION:
      return { Icon: MessageSquare, verb: "Asked you a question" };
    case ActionType.MESSAGE:
      if (action.source === "user") return null;
      return { Icon: MessageSquare, verb: "Replied" };
    case ActionType.FINISH:
      return { Icon: Sparkles, verb: "Finished" };
    case ActionType.REJECT:
      return { Icon: MessageSquare, verb: "Stopped" };
    default:
      return null;
  }
}

/**
 * Latest meaningful agent/tool activity for the top bar while the agent is active.
 */
export function deriveLiveActivity(
  events: ForgeEvent[],
  options: { streaming: boolean; isRunning: boolean },
): LiveActivity | null {
  if (options.streaming) {
    return { Icon: Sparkles, verb: "Writing reply" };
  }
  if (!options.isRunning) return null;

  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e === undefined) continue;
    if (!("action" in e)) continue;
    const a = e as ActionEvent;
    if (SILENT_ACTIONS.has(a.action as ActionType)) continue;
    if (a.source === "user" && a.action === ActionType.MESSAGE) continue;

    const hit = actionActivity(a);
    if (hit) return hit;
  }

  return { Icon: Loader2, verb: "Working…" };
}

/** User-facing lifecycle label + styling (top bar primary state). */
export function lifecycleDisplay(state: string): {
  label: string;
  textClass: string;
  dotClass: string;
  pulse: boolean;
} {
  switch (state) {
    case "loading":
      return {
        label: "Connecting…",
        textClass: "text-muted-foreground",
        dotClass: "bg-muted-foreground",
        pulse: true,
      };
    case "running":
      return {
        label: "Active",
        textClass: "text-emerald-600 dark:text-emerald-400",
        dotClass: "bg-emerald-500 dark:bg-emerald-400",
        pulse: true,
      };
    case "awaiting_user_input":
      return {
        label: "Ready for you",
        textClass: "text-sky-600 dark:text-sky-400",
        dotClass: "bg-sky-500 dark:bg-sky-400",
        pulse: false,
      };
    case "paused":
      return {
        label: "Paused",
        textClass: "text-amber-600 dark:text-amber-400",
        dotClass: "bg-amber-500 dark:bg-amber-400",
        pulse: false,
      };
    case "stopped":
      return {
        label: "Stopped",
        textClass: "text-muted-foreground",
        dotClass: "bg-muted-foreground",
        pulse: false,
      };
    case "finished":
      return {
        label: "Done",
        textClass: "text-emerald-600 dark:text-emerald-400",
        dotClass: "bg-emerald-500 dark:bg-emerald-400",
        pulse: false,
      };
    case "error":
      return {
        label: "Something went wrong",
        textClass: "text-destructive",
        dotClass: "bg-destructive",
        pulse: false,
      };
    case "awaiting_user_confirmation":
      return {
        label: "Needs your approval",
        textClass: "text-orange-600 dark:text-orange-400",
        dotClass: "bg-orange-500 dark:bg-orange-400",
        pulse: true,
      };
    case "rate_limited":
      return {
        label: "Rate limited",
        textClass: "text-amber-600 dark:text-amber-400",
        dotClass: "bg-amber-500 dark:bg-amber-400",
        pulse: false,
      };
    case "rejected":
      return {
        label: "Couldn’t complete",
        textClass: "text-muted-foreground",
        dotClass: "bg-muted-foreground",
        pulse: false,
      };
    default:
      return {
        label: state.replace(/_/g, " "),
        textClass: "text-muted-foreground",
        dotClass: "bg-muted-foreground",
        pulse: false,
      };
  }
}
