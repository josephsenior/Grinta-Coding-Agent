import { toast } from "sonner";
import type { ForgeEvent, ObservationEvent } from "@/types/events";
import { ObservationType } from "@/types/agent";
import { isRecoverableTransientErrorObservation } from "@/lib/transient-session-errors";

/** Turn literal `\n` sequences (common in embedded JSON/repr strings) into real newlines. */
export function normalizeDisplayNewlines(s: string): string {
  if (!s) return s;
  return s.replace(/\\n/g, "\n").replace(/\\t/g, "\t").replace(/\\r/g, "\r");
}

function isObservationEvent(ev: ForgeEvent): ev is ObservationEvent {
  return "observation" in ev;
}

/**
 * Errors shown as toast only — not persisted in the chat transcript.
 * - Backend sets `extras.notify_ui_only` for provider/key/quota style errors.
 * - Frontend also treats recoverable startup/connectivity errors the same way
 *   (see transient-session-errors.ts) so large red inline cards don't stick.
 */
export function isNotifyUiOnlyErrorEvent(ev: ForgeEvent): boolean {
  if (!isObservationEvent(ev) || ev.observation !== ObservationType.ERROR) return false;
  if (ev.extras?.notify_ui_only === true) return true;
  return isRecoverableTransientErrorObservation(ev);
}

function toastPayloadFromErrorObservation(ev: ObservationEvent): { title: string; description: string } {
  const raw = ev.content || ev.message || "Something went wrong";
  const trimmed = raw.trim();
  try {
    const parsed = JSON.parse(trimmed) as { title?: string; message?: string };
    if (parsed && typeof parsed === "object") {
      const title =
        typeof parsed.title === "string" && parsed.title.trim()
          ? parsed.title.trim()
          : "Error";
      const message =
        typeof parsed.message === "string" && parsed.message.trim()
          ? normalizeDisplayNewlines(parsed.message.trim())
          : normalizeDisplayNewlines(trimmed);
      return { title, description: message };
    }
  } catch {
    /* not JSON */
  }
  const lines = normalizeDisplayNewlines(trimmed).split(/\n+/);
  const title = lines[0]?.trim() || "Error";
  const rest = lines.slice(1).join("\n").trim();
  return {
    title,
    description: rest || normalizeDisplayNewlines(trimmed),
  };
}

export function toastNotifyUiOnlyError(ev: ObservationEvent): void {
  const { title, description } = toastPayloadFromErrorObservation(ev);
  toast.error(title, {
    description: description.length > 600 ? `${description.slice(0, 600)}…` : description,
    duration: 12_000,
  });
}
