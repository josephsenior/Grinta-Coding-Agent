import type { ForgeEvent, ObservationEvent } from "@/types/events";
import { AgentState, ObservationType } from "@/types/agent";

/**
 * Text patterns for error observations that are usually caused by temporary connectivity /
 * backend availability. After reconnect or health recovery, these are safe to drop from the
 * timeline so the UI matches current reality.
 */
const TRANSIENT_TEXT_RE = [
  /agent session failed to initialize/i,
  /failed to create agent session/i,
  /runtime initialization failed/i,
  /connection.*refused/i,
  /econnrefused/i,
  /network.*unreachable/i,
  /socket hang up/i,
  /fetch failed/i,
  /failed to fetch/i,
  /request timed out/i,
  /read timed out/i,
] as const;

function observationText(ev: ObservationEvent): string {
  const parts = [ev.content, ev.message];
  const reason = ev.extras?.reason;
  if (typeof reason === "string") parts.push(reason);
  return parts.filter(Boolean).join(" ");
}

/** Error observation whose message is typical of a recoverable outage. */
export function isRecoverableTransientErrorObservation(ev: ForgeEvent): boolean {
  if (!("observation" in ev) || ev.observation !== ObservationType.ERROR) return false;
  const text = observationText(ev as ObservationEvent);
  if (!text.trim()) return false;
  return TRANSIENT_TEXT_RE.some((re) => re.test(text));
}

/**
 * Startup failure pairs an ERROR card with AGENT_STATE_CHANGED → error; drop the state row too
 * when it matches the same class of failure.
 */
export function isRecoverableTransientAgentErrorState(ev: ForgeEvent): boolean {
  if (!("observation" in ev) || ev.observation !== ObservationType.AGENT_STATE_CHANGED) return false;
  const obs = ev as ObservationEvent;
  const state = obs.extras?.agent_state as AgentState | undefined;
  if (state !== AgentState.ERROR) return false;
  return TRANSIENT_TEXT_RE.some((re) => re.test(observationText(obs)));
}

export function isRecoverableTransientForgeEvent(ev: ForgeEvent): boolean {
  return isRecoverableTransientErrorObservation(ev) || isRecoverableTransientAgentErrorState(ev);
}
