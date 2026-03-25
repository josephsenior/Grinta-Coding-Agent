import { CheckCircle, XCircle, AlertTriangle, Wrench, Globe, BookOpen, PackageOpen, ArrowRightLeft, HelpCircle, BarChart3, ListChecks, MessageCircleQuestion } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ActionEvent, ObservationEvent } from "@/types/events";
import { ActionType, ActionSecurityRisk } from "@/types/agent";
import { cn } from "@/lib/utils";
import { ideToolShell, ideCaption } from "./chat-ide-styles";
import { CollapsibleToolOutput } from "./CollapsibleToolOutput";
import { normalizeDisplayNewlines } from "@/lib/error-observation";

const CONFIDENCE_WIDTH_CLASSES = [
  "w-[0%]",
  "w-[5%]",
  "w-[10%]",
  "w-[15%]",
  "w-[20%]",
  "w-[25%]",
  "w-[30%]",
  "w-[35%]",
  "w-[40%]",
  "w-[45%]",
  "w-[50%]",
  "w-[55%]",
  "w-[60%]",
  "w-[65%]",
  "w-[70%]",
  "w-[75%]",
  "w-[80%]",
  "w-[85%]",
  "w-[90%]",
  "w-[95%]",
  "w-[100%]",
] as const;

function confidenceWidthClass(confidence: number): string {
  const normalized = Number.isFinite(confidence) ? Math.max(0, Math.min(1, confidence)) : 0;
  return CONFIDENCE_WIDTH_CLASSES[Math.round(normalized * 20)] ?? "w-[0%]";
}

/* ═══ Action Cards ═══ */

interface ActionCardProps {
  event: ActionEvent;
}

/** Finish — green success banner. */
export function FinishCard({ event }: ActionCardProps) {
  return (
    <div className={cn(ideToolShell, "flex items-start gap-2 text-[13px] leading-snug text-foreground")}>
      <CheckCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span>{event.message || "Done."}</span>
    </div>
  );
}

/** Reject — agent couldn't complete. */
export function RejectCard({ event }: ActionCardProps) {
  return (
    <div className={cn(ideToolShell, "flex items-start gap-2 border-amber-500/20 bg-amber-500/5 text-[13px] leading-snug text-foreground dark:bg-amber-500/8")}>
      <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600/80 dark:text-amber-400/80" />
      <span>{event.message || "Could not complete task."}</span>
    </div>
  );
}

/** MCP tool call. */
export function McpCard({ event }: ActionCardProps) {
  const tool = String(event.args?.tool_name ?? "tool");
  const serverName = String(event.args?.server_name ?? "");

  return (
    <div className={cn(ideToolShell, "flex items-center gap-2 text-[12px] text-muted-foreground")}>
      <Wrench className="h-3.5 w-3.5 shrink-0 opacity-50" />
      <span>
        MCP{" "}
        <code className="rounded border border-border/40 bg-muted/50 px-1 font-mono text-[11px] dark:bg-card/45">{tool}</code>
        {serverName && (
          <span className="text-muted-foreground/60"> via {serverName}</span>
        )}
      </span>
    </div>
  );
}

/** LSP code-navigation query. */
export function LspQueryCard({ event }: ActionCardProps) {
  const command = String(event.args?.command ?? "query");
  const file = String(event.args?.file ?? "");
  const line = Number(event.args?.line ?? 1);
  const column = Number(event.args?.column ?? 1);

  return (
    <div className={cn(ideToolShell, "flex items-center gap-2 text-[12px] text-muted-foreground")}> 
      <BookOpen className="h-3.5 w-3.5 shrink-0 opacity-50" />
      <span>
        LSP <code className="rounded border border-border/40 bg-muted/50 px-1 font-mono text-[11px] dark:bg-card/45">{command}</code>
        {file && (
          <span className="text-muted-foreground/70"> at {file}:{Number.isFinite(line) ? line : 1}:{Number.isFinite(column) ? column : 1}</span>
        )}
      </span>
    </div>
  );
}

/** Browse / Browse Interactive — URL card. */
export function BrowseCard({ event }: ActionCardProps) {
  const url = String(event.args?.url ?? "");

  return (
    <div className={cn(ideToolShell, "flex items-center gap-2 text-[12px] text-muted-foreground")}>
      <Globe className="h-3.5 w-3.5 shrink-0 opacity-50" />
      <span>
        {event.action === ActionType.BROWSE_INTERACTIVE ? "Interactive browse" : "Browse"}
        {url && (
          <>
            {" "}
            <code className="inline-block max-w-xs truncate rounded border border-border/40 bg-muted/50 px-1 align-bottom font-mono text-[11px] dark:bg-card/45">
              {url}
            </code>
          </>
        )}
      </span>
    </div>
  );
}

/** Clarification — agent asks a question with options. */
export function ClarificationCard({ event }: ActionCardProps) {
  const question = event.message || String(event.args?.question ?? "");
  const options = event.args?.options as string[] | undefined;

  return (
    <div className={cn(ideToolShell, "space-y-2 p-3")}>
      <div className="flex items-start gap-2">
        <MessageCircleQuestion className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className={cn(ideCaption, "font-medium text-foreground")}>Question</span>
      </div>
      <p className="text-[13px] leading-relaxed text-foreground">{question}</p>
      {options && options.length > 0 && (
        <ol className="ml-4 list-decimal space-y-1 text-[12px] text-foreground/90">
          {options.map((opt, i) => (
            <li key={i}>{opt}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** Escalation — agent needs human help. */
export function EscalateCard({ event }: ActionCardProps) {
  const reason = event.message || String(event.args?.reason ?? "");
  const helpNeeded = String(event.args?.specific_help_needed ?? "");

  return (
    <div className={cn(ideToolShell, "space-y-2 border-orange-500/20 bg-orange-500/5 p-3 dark:bg-orange-500/8")}>
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-orange-600/80 dark:text-orange-400/75" />
        <span className={cn(ideCaption, "font-medium text-foreground")}>Needs input</span>
      </div>
      <p className="text-[13px] leading-relaxed text-foreground">{reason}</p>
      {helpNeeded && (
        <p className="text-[11px] italic text-muted-foreground">{helpNeeded}</p>
      )}
    </div>
  );
}

/** Proposal — numbered options with a recommendation. */
export function ProposalCard({ event }: ActionCardProps) {
  const options = event.args?.options as string[] | undefined;
  const recommended = event.args?.recommended as number | undefined;

  return (
    <div className={cn(ideToolShell, "space-y-2 p-3")}>
      <div className="flex items-start gap-2">
        <ListChecks className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className={cn(ideCaption, "font-medium text-foreground")}>Options</span>
      </div>
      {event.message && <p className="text-[13px] leading-relaxed">{event.message}</p>}
      {options && options.length > 0 && (
        <ol className="ml-4 list-decimal space-y-1 text-[12px]">
          {options.map((opt, i) => (
            <li
              key={i}
              className={
                recommended !== undefined && i === recommended
                  ? "font-medium text-primary"
                  : ""
              }
            >
              {opt}
              {recommended !== undefined && i === recommended && (
                <Badge variant="outline" className="ml-2 text-[10px]">
                  recommended
                </Badge>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** Uncertainty — shows confidence + concerns. */
export function UncertaintyCard({ event }: ActionCardProps) {
  const confidence = event.args?.confidence as number | undefined;
  const concerns = event.args?.concerns as string[] | undefined;

  return (
    <div className={cn(ideToolShell, "space-y-2 p-3")}>
      <div className="flex items-start gap-2">
        <HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className={cn(ideCaption, "font-medium text-foreground")}>Confidence</span>
      </div>
      {event.message && <p className="text-[13px] leading-relaxed">{event.message}</p>}
      {confidence !== undefined && (
        <div className="mt-2 flex items-center gap-2">
          <BarChart3 className="h-3.5 w-3.5" />
          <div className="h-2 flex-1 rounded-full bg-muted">
            <div className={`h-2 rounded-full bg-primary transition-all ${confidenceWidthClass(confidence)}`} />
          </div>
          <span className="text-xs font-mono">{Math.round(confidence * 100)}%</span>
        </div>
      )}
      {concerns && concerns.length > 0 && (
        <ul className="mt-2 ml-5 list-disc space-y-1 text-xs text-muted-foreground">
          {concerns.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Delegate task. */
export function DelegateCard({ event }: ActionCardProps) {
  return (
    <div className={cn(ideToolShell, "flex items-center gap-2 text-[11px] text-muted-foreground")}>
      <ArrowRightLeft className="h-3 w-3 shrink-0 opacity-50" />
      <span>
        Delegated: {event.message || String(event.args?.task ?? "")}
      </span>
    </div>
  );
}

/** Condensation / recall action. */
export function CondensationCard({ event }: ActionCardProps) {
  const isRecall = event.action === ActionType.RECALL;
  const key = String(event.args?.key ?? event.args?.query ?? "");

  return (
    <div className={cn(ideToolShell, "flex items-center gap-2 text-[11px] text-muted-foreground")}>
      {isRecall ? (
        <BookOpen className="h-3 w-3 shrink-0 opacity-50" />
      ) : (
        <PackageOpen className="h-3 w-3 shrink-0 opacity-50" />
      )}
      <span>
        {isRecall ? "Recalled" : "Context condensed"}
        {key && `: ${key}`}
      </span>
    </div>
  );
}

/* ═══ Observation Cards ═══ */

interface ObservationCardProps {
  event: ObservationEvent;
}

/** Error observation. */
export function ErrorCard({ event }: ObservationCardProps) {
  const category = event.extras?.error_category as string | undefined;
  const severity = event.extras?.severity as string | undefined;
  const text = normalizeDisplayNewlines(event.content || event.message || "");

  return (
    <div className={cn(ideToolShell, "border-destructive/25 bg-destructive/5 p-3 dark:bg-destructive/10")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />
          <span className={cn(ideCaption, "font-medium text-destructive")}>Error</span>
        </div>
        {(category || severity) && (
          <div className="flex flex-wrap gap-1.5">
            {category && (
              <Badge variant="outline" className="text-[10px]">
                {category}
              </Badge>
            )}
            {severity && (
              <Badge
                variant={severity === "critical" || severity === "error" ? "destructive" : "outline"}
                className="text-[10px]"
              >
                {severity}
              </Badge>
            )}
          </div>
        )}
      </div>
      <CollapsibleToolOutput
        content={text}
        previewLines={6}
        collapseWhenLines={12}
        collapseWhenChars={2200}
        emptyText="(no error details)"
        className="mt-2"
        preClassName="rounded border border-destructive/25 bg-destructive/5 p-2 text-[12px] leading-relaxed text-destructive dark:bg-destructive/15"
      />
    </div>
  );
}

/** MCP observation result. */
export function McpObservationCard({ event }: ObservationCardProps) {
  return (
    <div className={cn(ideToolShell, "text-[11px] text-muted-foreground")}>
      <div className="mb-1 flex items-center gap-1.5">
        <Wrench className="h-3 w-3 shrink-0 opacity-50" />
        <span className={ideCaption}>MCP result</span>
      </div>
      {event.content && (
        <CollapsibleToolOutput
          content={event.content}
          previewLines={5}
          collapseWhenLines={10}
          collapseWhenChars={2000}
          className="mt-1"
          preClassName="rounded border border-border/40 bg-muted/45 p-2 dark:bg-card/40"
        />
      )}
    </div>
  );
}

/** LSP query result observation. */
export function LspObservationCard({ event }: ObservationCardProps) {
  const unavailable = String(event.message || "").toLowerCase().includes("unavailable");
  return (
    <div className={cn(ideToolShell, "text-[11px] text-muted-foreground")}> 
      <div className="mb-1 flex items-center gap-1.5">
        <BookOpen className="h-3 w-3 shrink-0 opacity-50" />
        <span className={ideCaption}>{unavailable ? "LSP unavailable" : "LSP result"}</span>
      </div>
      {event.content && (
        <CollapsibleToolOutput
          content={event.content}
          previewLines={6}
          collapseWhenLines={12}
          collapseWhenChars={2200}
          className="mt-1"
          preClassName="rounded border border-border/40 bg-muted/45 p-2 dark:bg-card/40"
        />
      )}
    </div>
  );
}

/** Browse observation. */
export function BrowseObservationCard({ event }: ObservationCardProps) {
  const url = event.extras?.url as string | undefined;

  return (
    <div className={cn(ideToolShell, "text-[11px] text-muted-foreground")}>
      <div className="mb-1 flex items-center gap-1.5">
        <Globe className="h-3 w-3 shrink-0 opacity-50" />
        <span className={ideCaption}>
          Browse{url && `: ${url}`}
        </span>
      </div>
      {event.content && (
        <CollapsibleToolOutput
          content={event.content}
          previewLines={5}
          collapseWhenLines={10}
          collapseWhenChars={1800}
          className="mt-1"
          preClassName="rounded border border-border/40 bg-muted/45 p-2 dark:bg-card/40"
        />
      )}
    </div>
  );
}

/** Delegate task result observation. */
export function DelegateResultCard({ event }: ObservationCardProps) {
  const text = event.content || event.message || "";

  return (
    <div className={cn(ideToolShell, "text-[11px] text-muted-foreground")}>
      <div className="mb-1 flex items-center gap-1.5">
        <ArrowRightLeft className="h-3 w-3 shrink-0 opacity-50" />
        <span className={ideCaption}>Sub-task result</span>
      </div>
      <CollapsibleToolOutput
        content={text}
        previewLines={5}
        collapseWhenLines={10}
        collapseWhenChars={2000}
        emptyText="(empty)"
        preClassName="rounded border border-border/40 bg-muted/45 p-2 text-foreground/90 dark:bg-card/40"
      />
    </div>
  );
}

/** Recall failure observation. */
export function RecallFailureCard({ event }: ObservationCardProps) {
  const text = event.content || event.message || "";

  return (
    <div className={cn(ideToolShell, "border-amber-500/20 bg-amber-500/5 text-[11px] text-muted-foreground dark:bg-amber-500/8")}>
      <div className="mb-1 flex items-center gap-1.5">
        <BookOpen className="h-3 w-3 shrink-0 text-amber-600/80 dark:text-amber-400/75" />
        <span className={ideCaption}>Recall failed</span>
      </div>
      <CollapsibleToolOutput
        content={text}
        previewLines={5}
        collapseWhenLines={10}
        collapseWhenChars={1800}
        emptyText="(no details)"
        preClassName="rounded border border-amber-500/20 bg-muted/40 p-2 text-foreground/90 dark:bg-card/35"
      />
    </div>
  );
}

/** Agent state change — renders as a minimal inline status pill. */
export function AgentStateChangedPill({ event }: ObservationCardProps) {
  const newState = event.extras?.agent_state as string | undefined;
  if (!newState) return null;

  // Only show certain transitions as inline pills
  const labels: Record<string, string> = {
    running: "Agent started working",
    awaiting_user_input: "Agent is waiting for your input",
    paused: "Agent paused",
    stopped: "Agent stopped",
    finished: "Agent finished",
    error: "Agent encountered an error",
    rate_limited: "Agent was rate limited",
  };

  const label = labels[newState];
  if (!label) return null;

  return (
    <div className="flex justify-center py-1">
      <span className="rounded-full bg-muted px-3 py-0.5 text-[11px] text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

/** Security risk hint for confirmation — whisper-weight, not a loud alert. */
export function SecurityRiskBadge({ risk }: { risk: ActionSecurityRisk | undefined }) {
  if (risk === undefined || risk === ActionSecurityRisk.UNKNOWN) return null;

  const config = {
    [ActionSecurityRisk.LOW]: {
      label: "Low",
      title: "Assessed security risk: low",
      className:
        "bg-emerald-500/8 text-emerald-900/85 ring-emerald-500/15 dark:text-emerald-300/90",
    },
    [ActionSecurityRisk.MEDIUM]: {
      label: "Medium",
      title: "Assessed security risk: medium",
      className:
        "bg-amber-500/8 text-amber-950/90 ring-amber-500/15 dark:text-amber-200/85",
    },
    [ActionSecurityRisk.HIGH]: {
      label: "High",
      title: "Assessed security risk: high — review carefully",
      className:
        "bg-destructive/8 text-destructive ring-destructive/20 dark:text-red-300/90",
    },
  };

  const c = config[risk as keyof typeof config];
  if (!c) return null;

  return (
    <span
      title={c.title}
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-normal tracking-wide ring-1",
        c.className,
      )}
    >
      {c.label}
    </span>
  );
}
