import { useMemo, useState } from "react";
import { CheckCircle2, ChevronRight, CircleDotDashed, FileText, TerminalSquare, Wrench, Loader2 } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ActionType } from "@/types/agent";
import type { ForgeEvent } from "@/types/events";
import { buildTimelineSteps } from "@/lib/timeline-steps";
import { EventCard } from "./EventRenderer";

interface TimelineStepsProps {
  events: ForgeEvent[];
  thinkDurationByEventId?: Map<number, number>;
}

export function TimelineSteps({ events, thinkDurationByEventId }: TimelineStepsProps) {
  const steps = useMemo(() => buildTimelineSteps(events), [events]);
  const [openMap, setOpenMap] = useState<Record<string, boolean>>({});

  if (steps.length === 0) return null;

  return (
    <div className="space-y-3">
      {steps.map((step, index) => {
        const defaultOpen = index >= steps.length - 2;
        const isOpen = openMap[step.id] ?? defaultOpen;
        const StatusIcon =
          step.status === "done"
            ? CheckCircle2
            : step.status === "needs_attention"
              ? CircleDotDashed
              : Loader2;

        return (
          <div key={step.id} className="flex flex-col gap-3">
            {step.events
              .filter((e) => "action" in e && e.action === ActionType.MESSAGE && e.source === "user")
              .map((event, i) => (
                <EventCard
                  key={`user-${event.id || i}`}
                  event={event}
                  thinkDurationMs={event.id != null ? thinkDurationByEventId?.get(Number(event.id)) : undefined}
                />
              ))}

            {step.events.some((e) => !("action" in e && e.action === ActionType.MESSAGE)) && (
              <Collapsible
                open={isOpen}
                onOpenChange={(open) =>
                  setOpenMap((prev) => ({
                    ...prev,
                    [step.id]: open,
                  }))
                }
                className="rounded-xl border border-border/45 bg-card/70 px-3 py-2"
              >
                <CollapsibleTrigger className="w-full text-left">
                  <div className="flex items-start gap-2">
                    <ChevronRight
                      className={cn("mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusIcon
                          className={cn(
                            "h-3.5 w-3.5 shrink-0",
                            step.status === "done" && "text-emerald-500",
                            step.status === "needs_attention" && "text-amber-500",
                            step.status === "running" && "text-sky-500 animate-spin"
                          )}
                        />
                        <span className="truncate text-[12px] font-semibold text-foreground">{step.title}</span>
                      </div>
                      <p className="mt-0.5 text-[11px] text-muted-foreground">{step.summary}</p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                        {step.stats.fileOps > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-muted/45 px-2 py-0.5">
                            <FileText className="h-3 w-3" />
                            {step.stats.fileOps} file ops
                          </span>
                        )}
                        {step.stats.commands > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-muted/45 px-2 py-0.5">
                            <TerminalSquare className="h-3 w-3" />
                            {step.stats.commands} commands
                          </span>
                        )}
                        {step.stats.toolCalls > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-muted/45 px-2 py-0.5">
                            <Wrench className="h-3 w-3" />
                            {step.stats.toolCalls} tools
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </CollapsibleTrigger>

                <CollapsibleContent className="data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0">
                  <div className="mt-2 space-y-3 border-l border-border/40 pl-4">
                    {step.events
                      .filter((e) => !("action" in e && e.action === ActionType.MESSAGE))
                      .map((event, i) => (
                        <EventCard
                          key={event.id != null ? `e-${event.id}` : `i-${i}`}
                          event={event}
                          thinkDurationMs={event.id != null ? thinkDurationByEventId?.get(Number(event.id)) : undefined}
                        />
                      ))}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}

            {step.events
              .filter((e) => "action" in e && e.action === ActionType.MESSAGE && e.source !== "user")
              .map((event, i) => (
                <EventCard
                  key={`agent-${event.id || i}`}
                  event={event}
                  thinkDurationMs={event.id != null ? thinkDurationByEventId?.get(Number(event.id)) : undefined}
                />
              ))}
          </div>
        );
      })}
    </div>
  );
}
