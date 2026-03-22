import { toast } from "sonner";
import type { ForgeEvent, ObservationEvent } from "@/types/events";
import { ObservationType } from "@/types/agent";

/** Matches backend `WORKSPACE_NOT_OPEN_ERROR_ID` in workspace_resolution / runtime. */
export const WORKSPACE_NOT_OPEN_ERROR_ID = "WORKSPACE$NOT_OPEN";

const _shownWorkspaceToastForConversation = new Set<string>();

/**
 * One friendly toast per conversation when a tool hits “no project folder open”.
 * Errors still appear on the timeline so the agent can recover after the user opens a folder.
 */
export function maybeToastWorkspaceNotOpen(
  ev: ForgeEvent,
  conversationId: string | null,
): void {
  if (!conversationId || conversationId === "new") return;
  if (!("observation" in ev) || ev.observation !== ObservationType.ERROR) return;

  const obs = ev as ObservationEvent;
  const ex = obs.extras ?? {};
  const idMatch = ex.error_id === WORKSPACE_NOT_OPEN_ERROR_ID;
  const content = (obs.content || obs.message || "").toString();
  const textMatch = content.includes("No project folder is open");
  if (!idMatch && !textMatch) return;

  if (_shownWorkspaceToastForConversation.has(conversationId)) return;
  _shownWorkspaceToastForConversation.add(conversationId);

  toast.info("Open a workspace for file & git tools", {
    description:
      "Use the sidebar → Open workspace and pick your project folder. You can still chat without one.",
    duration: 10_000,
  });
}
