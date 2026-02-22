import { CheckCircle, XCircle, AlertTriangle, Wrench, Globe, BookOpen, PackageOpen, ArrowRightLeft, HelpCircle, BarChart3, ListChecks, MessageCircleQuestion } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ActionEvent, ObservationEvent } from "@/types/events";
import { ActionType, ActionSecurityRisk } from "@/types/agent";

/* ═══ Action Cards ═══ */

interface ActionCardProps {
  event: ActionEvent;
}

/** Finish — green success banner. */
export function FinishCard({ event }: ActionCardProps) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-green-500/20 bg-green-500/10 p-3 text-sm text-green-700 dark:text-green-400">
      <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{event.message || "Task complete"}</span>
    </div>
  );
}

/** Reject — agent couldn't complete. */
export function RejectCard({ event }: ActionCardProps) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-yellow-500/20 bg-yellow-500/10 p-3 text-sm text-yellow-700 dark:text-yellow-400">
      <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{event.message || "Could not complete task"}</span>
    </div>
  );
}

/** MCP tool call. */
export function McpCard({ event }: ActionCardProps) {
  const tool = String(event.args?.tool_name ?? "tool");
  const serverName = String(event.args?.server_name ?? "");

  return (
    <div className="flex items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground">
      <Wrench className="h-3.5 w-3.5 shrink-0" />
      <span>
        MCP: <code className="rounded bg-muted px-1 font-mono">{tool}</code>
        {serverName && (
          <span className="text-muted-foreground/60"> via {serverName}</span>
        )}
      </span>
    </div>
  );
}

/** Browse / Browse Interactive — URL card. */
export function BrowseCard({ event }: ActionCardProps) {
  const url = String(event.args?.url ?? "");

  return (
    <div className="flex items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground">
      <Globe className="h-3.5 w-3.5 shrink-0" />
      <span>
        {event.action === ActionType.BROWSE_INTERACTIVE ? "Interactive browse" : "Browse"}
        {url && (
          <>
            {" "}
            <code className="rounded bg-muted px-1 font-mono truncate max-w-xs inline-block align-bottom">
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
    <div className="rounded-lg border border-blue-500/20 bg-blue-500/10 p-3 text-sm">
      <div className="flex items-start gap-2 text-blue-700 dark:text-blue-400">
        <MessageCircleQuestion className="mt-0.5 h-4 w-4 shrink-0" />
        <span className="font-medium">Clarification needed</span>
      </div>
      <p className="mt-2 text-foreground">{question}</p>
      {options && options.length > 0 && (
        <ol className="mt-2 ml-5 list-decimal space-y-1 text-sm">
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
    <div className="rounded-lg border border-orange-500/20 bg-orange-500/10 p-3 text-sm">
      <div className="flex items-start gap-2 text-orange-700 dark:text-orange-400">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span className="font-medium">Agent needs help</span>
      </div>
      <p className="mt-2 text-foreground">{reason}</p>
      {helpNeeded && (
        <p className="mt-1 text-muted-foreground text-xs italic">{helpNeeded}</p>
      )}
    </div>
  );
}

/** Proposal — numbered options with a recommendation. */
export function ProposalCard({ event }: ActionCardProps) {
  const options = event.args?.options as string[] | undefined;
  const recommended = event.args?.recommended as number | undefined;

  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex items-start gap-2 text-muted-foreground">
        <ListChecks className="mt-0.5 h-4 w-4 shrink-0" />
        <span className="font-medium text-foreground">Proposal</span>
      </div>
      {event.message && <p className="mt-2">{event.message}</p>}
      {options && options.length > 0 && (
        <ol className="mt-2 ml-5 list-decimal space-y-1 text-sm">
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
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex items-start gap-2 text-muted-foreground">
        <HelpCircle className="mt-0.5 h-4 w-4 shrink-0" />
        <span className="font-medium text-foreground">Uncertainty</span>
      </div>
      {event.message && <p className="mt-2">{event.message}</p>}
      {confidence !== undefined && (
        <div className="mt-2 flex items-center gap-2">
          <BarChart3 className="h-3.5 w-3.5" />
          <div className="h-2 flex-1 rounded-full bg-muted">
            <div
              className="h-2 rounded-full bg-primary transition-all"
              style={{ width: `${Math.round(confidence * 100)}%` }}
            />
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
    <div className="flex items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground">
      <ArrowRightLeft className="h-3.5 w-3.5 shrink-0" />
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
    <div className="flex items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground">
      {isRecall ? (
        <BookOpen className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <PackageOpen className="h-3.5 w-3.5 shrink-0" />
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

  return (
    <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-3 text-sm">
      <div className="flex items-start gap-2">
        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
        <span className="text-destructive">{event.content || event.message}</span>
      </div>
      {(category || severity) && (
        <div className="mt-2 flex gap-1.5">
          {category && (
            <Badge variant="outline" className="text-[10px]">
              {category}
            </Badge>
          )}
          {severity && (
            <Badge variant={severity === "critical" || severity === "error" ? "destructive" : "outline"} className="text-[10px]">
              {severity}
            </Badge>
          )}
        </div>
      )}
    </div>
  );
}

/** MCP observation result. */
export function McpObservationCard({ event }: ObservationCardProps) {
  return (
    <div className="rounded-lg border p-2 text-xs text-muted-foreground">
      <div className="flex items-center gap-2">
        <Wrench className="h-3.5 w-3.5 shrink-0" />
        <span>MCP result</span>
      </div>
      {event.content && (
        <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-zinc-600 dark:text-zinc-400">
          {event.content.length > 2000
            ? event.content.slice(0, 2000) + "\n..."
            : event.content}
        </pre>
      )}
    </div>
  );
}

/** Browse observation. */
export function BrowseObservationCard({ event }: ObservationCardProps) {
  const url = event.extras?.url as string | undefined;

  return (
    <div className="rounded-lg border p-2 text-xs text-muted-foreground">
      <div className="flex items-center gap-2">
        <Globe className="h-3.5 w-3.5 shrink-0" />
        <span>
          Browse result{url && `: ${url}`}
        </span>
      </div>
      {event.content && (
        <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-zinc-600 dark:text-zinc-400">
          {event.content.length > 1000
            ? event.content.slice(0, 1000) + "\n..."
            : event.content}
        </pre>
      )}
    </div>
  );
}

/** Delegate task result observation. */
export function DelegateResultCard({ event }: ObservationCardProps) {
  return (
    <div className="flex items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground">
      <ArrowRightLeft className="h-3.5 w-3.5 shrink-0" />
      <span>Sub-task result: {event.content || event.message}</span>
    </div>
  );
}

/** Recall failure observation. */
export function RecallFailureCard({ event }: ObservationCardProps) {
  return (
    <div className="flex items-center gap-2 rounded-lg border p-2 text-xs text-muted-foreground">
      <BookOpen className="h-3.5 w-3.5 shrink-0 text-yellow-500" />
      <span>Recall failed: {event.content || event.message}</span>
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

/** Security risk badge for confirmation. */
export function SecurityRiskBadge({ risk }: { risk: ActionSecurityRisk | undefined }) {
  if (risk === undefined || risk === ActionSecurityRisk.UNKNOWN) return null;

  const config = {
    [ActionSecurityRisk.LOW]: { label: "Low Risk", variant: "success" as const },
    [ActionSecurityRisk.MEDIUM]: { label: "Medium Risk", variant: "warning" as const },
    [ActionSecurityRisk.HIGH]: { label: "High Risk", variant: "destructive" as const },
  };

  const c = config[risk as keyof typeof config];
  if (!c) return null;

  return <Badge variant={c.variant}>{c.label}</Badge>;
}
