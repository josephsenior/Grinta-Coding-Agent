import { useCallback, useState, useMemo, useRef, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Send,
  Square,
  Play,
  Loader2,
  PanelRightOpen,
  PanelRightClose,
  ArrowDown,
  CheckSquare,
  Clock,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  Settings,
  AlertTriangle,
  MessageSquare,
  Sparkles,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { useConversation } from "@/hooks/use-conversations";
import { usePlaybooks } from "@/hooks/use-playbooks";
import { useSocket } from "@/hooks/use-socket";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useSessionStore } from "@/stores/session-store";
import { useAppStore } from "@/stores/app-store";
import { sendUserAction } from "@/socket/client";
import { toast } from "sonner";
import { AgentState, ActionType, ObservationType } from "@/types/agent";
import type { ActionEvent, ForgeEvent } from "@/types/events";
import { EventCard } from "@/components/chat/EventRenderer";
import { AgentWorkflowGroup } from "@/components/chat/AgentWorkflowGroup";
import { StreamingBubble } from "@/components/chat/StreamingBubble";
import { ConfirmationBanner } from "@/components/chat/ConfirmationBanner";
import { PlaybookAutocomplete } from "@/components/chat/PlaybookAutocomplete";
import { ContextPanel } from "@/components/context-panel/ContextPanel";
import { getSettings } from "@/api/settings";
import { cn } from "@/lib/utils";

// --- Inline Tasks Strip ---
type TaskStatus = "open" | "in_progress" | "completed" | "abandoned";

interface Task {
  id: string;
  goal: string;
  status: TaskStatus;
  subtasks?: Task[];
}

const TASK_DEPTH_CLASSES = [
  "pl-1",
  "pl-[18px]",
  "pl-8",
  "pl-[46px]",
  "pl-[60px]",
  "pl-[74px]",
  "pl-[88px]",
  "pl-[102px]",
  "pl-[116px]",
] as const;

function taskDepthClass(depth: number): string {
  const normalizedDepth = Math.max(0, Math.min(TASK_DEPTH_CLASSES.length - 1, depth));
  return TASK_DEPTH_CLASSES[normalizedDepth] ?? TASK_DEPTH_CLASSES[0];
}

function taskIcon(status: TaskStatus) {
  switch (status) {
    case "completed": return <CheckCircle2 className="h-3 w-3 shrink-0 text-green-500" />;
    case "abandoned": return <XCircle className="h-3 w-3 shrink-0 text-red-400" />;
    case "in_progress": return <Clock className="h-3 w-3 shrink-0 text-blue-400 animate-pulse" />;
    default: return <CheckSquare className="h-3 w-3 shrink-0 text-muted-foreground" />;
  }
}

function TaskRow({ task, depth = 0 }: { task: Task; depth?: number }) {
  return (
    <div>
      <div className={cn("flex items-start gap-1.5 py-0.5", taskDepthClass(depth))}>
        {taskIcon(task.status)}
        <span className={cn(
          "text-xs leading-snug",
          task.status === "completed" && "line-through text-muted-foreground",
          task.status === "abandoned" && "line-through opacity-40",
        )}>
          {task.goal}
        </span>
      </div>
      {task.subtasks?.map((sub) => (
        <TaskRow key={sub.id} task={sub} depth={depth + 1} />
      ))}
    </div>
  );
}

function InlineTasksPanel() {
  const [expanded, setExpanded] = useState(true);
  const events = useSessionStore((s) => s.events);

  const taskEvents = events.filter(
    (e): e is ActionEvent => "action" in e && e.action === ActionType.TASK_TRACKING,
  );
  const latestTaskEvent = taskEvents[taskEvents.length - 1];
  const tasks: Task[] = latestTaskEvent
    ? ((latestTaskEvent.args?.tasks as Task[] | undefined) ?? [])
    : [];

  if (tasks.length === 0) return null;

  const activeTasks = tasks.filter((t) => t.status === "in_progress").length;
  const doneTasks = tasks.filter((t) => t.status === "completed").length;

  return (
    <div className="border-b bg-muted/20 shrink-0">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-1.5 text-xs hover:bg-muted/40 transition-colors"
      >
        <CheckSquare className="h-3 w-3 text-muted-foreground shrink-0" />
        <span className="font-medium text-muted-foreground">Tasks</span>
        <Badge variant="secondary" className="h-4 px-1.5 text-[10px] font-normal">
          {doneTasks}/{tasks.length}
        </Badge>
        {activeTasks > 0 && (
          <Badge variant="default" className="h-4 px-1.5 text-[10px] font-normal">
            {activeTasks} active
          </Badge>
        )}
        <span className="ml-auto text-muted-foreground">
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </span>
      </button>
      {expanded && (
        <div className="max-h-44 overflow-y-auto px-4 pb-2">
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </div>
      )}
    </div>
  );
}

// --- Agent state display ---
function agentStateDisplay(state: AgentState) {
  switch (state) {
    case AgentState.LOADING:
      return { label: "Starting...", color: "text-muted-foreground", pulse: true };
    case AgentState.RUNNING:
      return { label: "Working", color: "text-green-500", pulse: true };
    case AgentState.AWAITING_USER_INPUT:
      return { label: "Your turn", color: "text-blue-500", pulse: false };
    case AgentState.PAUSED:
      return { label: "Paused", color: "text-yellow-500", pulse: false };
    case AgentState.STOPPED:
      return { label: "Stopped", color: "text-muted-foreground", pulse: false };
    case AgentState.FINISHED:
      return { label: "Complete", color: "text-green-500", pulse: false };
    case AgentState.ERROR:
      return { label: "Error", color: "text-destructive", pulse: false };
    case AgentState.AWAITING_USER_CONFIRMATION:
      return { label: "Needs approval", color: "text-orange-500", pulse: true };
    case AgentState.RATE_LIMITED:
      return { label: "Rate limited", color: "text-yellow-500", pulse: false };
    default:
      return { label: state, color: "text-muted-foreground", pulse: false };
  }
}

// --- Setup banner for missing configuration ---
function SetupBanner({ apiKeySet, modelSet }: { apiKeySet: boolean; modelSet: boolean }) {
  if (apiKeySet && modelSet) return null;

  return (
    <div className="mx-auto w-full max-w-2xl">
      <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-yellow-500/10">
            <AlertTriangle className="h-4 w-4 text-yellow-500" />
          </div>
          <div className="flex-1 space-y-1">
            <p className="text-sm font-medium">Configuration needed</p>
            <p className="text-xs text-muted-foreground">
              {!modelSet && !apiKeySet
                ? "Set up your LLM model and API key to start using the agent."
                : !apiKeySet
                  ? "Add your API key so the agent can communicate with the LLM."
                  : "Choose an LLM model for the agent to use."}
            </p>
            <Button variant="outline" size="sm" className="mt-2 h-7 gap-1.5 text-xs" asChild>
              <Link to="/settings">
                <Settings className="h-3 w-3" />
                Open Settings
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Welcome empty state ---
function WelcomeState() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-5 py-16 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
        <Sparkles className="h-7 w-7 text-primary" />
      </div>
      <div className="space-y-2">
        <h2 className="text-lg font-semibold">Systems Online</h2>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Input mission parameters below to deploy an agent. It can synthesize code, resolve exceptions, execute workflows, or analyze the workspace structure.
        </p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        {["Resolve test pipeline exceptions", "Architectural refactoring", "Decompile logic intent"].map((hint) => (
          <span
            key={hint}
            className="rounded-full border bg-muted/50 px-3 py-1 text-xs text-muted-foreground"
          >
            {hint}
          </span>
        ))}
      </div>
    </div>
  );
}

type GroupedEventItem = 
  | { type: "single"; event: ForgeEvent }
  | { type: "workflow"; id: string; events: ForgeEvent[] };

function isPrimaryEvent(event: ForgeEvent): boolean {
  if ("action" in event) {
    return [
      ActionType.MESSAGE,
      ActionType.CLARIFICATION,
      ActionType.PROPOSAL,
      ActionType.ESCALATE,
      ActionType.UNCERTAINTY,
      ActionType.FINISH,
      ActionType.REJECT
    ].includes(event.action as ActionType);
  }
  if ("observation" in event) {
    return [
      ObservationType.MESSAGE,
      ObservationType.CHAT,
      ObservationType.USER_REJECTED
    ].includes(event.observation as ObservationType);
  }
  return false;
}

export default function Chat() {
  const { id } = useParams<{ id: string }>();
  const { data: conversation } = useConversation(id);
  const { data: playbooks = [] } = usePlaybooks(id);

  useSocket(id);

  const events = useSessionStore((s) => s.events);

  const groupedEvents = useMemo(() => {
    const groups: GroupedEventItem[] = [];
    let currentWorkflow: ForgeEvent[] = [];

    for (const event of events) {
      if (isPrimaryEvent(event)) {
        if (currentWorkflow.length > 0) {
          groups.push({ type: "workflow", id: `wf-${currentWorkflow[0]?.id ?? groups.length}`, events: currentWorkflow });
          currentWorkflow = [];
        }
        groups.push({ type: "single", event });
      } else {
        // Exclude completely silent internal events from the workflow group
        // EventRenderer handles skipping but grouping them empty is weird
        // We'll let EventRenderer internally drop them anyway, but it's fine
        currentWorkflow.push(event);
      }
    }
    
    if (currentWorkflow.length > 0) {
      groups.push({ type: "workflow", id: `wf-${currentWorkflow[0]?.id ?? groups.length}`, events: currentWorkflow });
    }
    
    return groups;
  }, [events]);

  const agentState = useSessionStore((s) => s.agentState);
  const streamingContent = useSessionStore((s) => s.streamingContent);
  const isConnected = useSessionStore((s) => s.isConnected);
  const isReconnecting = useSessionStore((s) => s.isReconnecting);
  const contextPanelOpen = useAppStore((s) => s.contextPanelOpen);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);

  const [inputValue, setInputValue] = useState("");
  const [contextWidth, setContextWidth] = useState(380);
  const isDragging = useRef(false);
  const contextPanelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (contextPanelRef.current) {
      contextPanelRef.current.style.width = `${contextWidth}px`;
    }
  }, [contextWidth]);

  // Fetch settings to know if the API key / model are configured
  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
    staleTime: 30_000,
    retry: 1,
  });

  const apiKeySet = settings?.llm_api_key_set ?? true; // default true to avoid flash
  const modelSet = !!settings?.llm_model;

  // -- Stuck-state detection --
  // If agentState is LOADING for more than 5s and we have no events, treat it as idle
  const [loadingTimedOut, setLoadingTimedOut] = useState(false);
  useEffect(() => {
    if (agentState !== AgentState.LOADING) {
      setLoadingTimedOut(false);
      return;
    }
    const timer = setTimeout(() => setLoadingTimedOut(true), 5000);
    return () => clearTimeout(timer);
  }, [agentState]);

  // Intermediate stall warning: if RUNNING for 30s with no new events/streaming,
  // show a soft "taking longer than expected" message to reassure the user.
  const [runningSlow, setRunningSlow] = useState(false);
  useEffect(() => {
    if (agentState !== AgentState.RUNNING) {
      setRunningSlow(false);
      return;
    }
    const timer = setTimeout(() => setRunningSlow(true), 30_000);
    return () => clearTimeout(timer);
  }, [agentState, events.length, streamingContent]);

  // If agentState is RUNNING for more than 90s with no new events or streaming,
  // allow user to send a message or stop the agent (un-stick the UI).
  const [runningTimedOut, setRunningTimedOut] = useState(false);
  useEffect(() => {
    if (agentState !== AgentState.RUNNING) {
      setRunningTimedOut(false);
      return;
    }
    const timer = setTimeout(() => setRunningTimedOut(true), 90_000);
    return () => clearTimeout(timer);
  }, [agentState, events.length, streamingContent]);

  // Use conversation REST metadata to seed the agent state before the first socket event arrives.
  // If we've timed out waiting for events, fall back to AWAITING_USER_INPUT so the user can type.
  const effectiveAgentState: AgentState = useMemo(() => {
    if (agentState !== AgentState.LOADING) return agentState;
    if (conversation?.agent_state && conversation.agent_state !== "loading") {
      return conversation.agent_state as AgentState;
    }
    if (loadingTimedOut) return AgentState.AWAITING_USER_INPUT;
    return AgentState.LOADING;
  }, [agentState, conversation?.agent_state, loadingTimedOut]);

  // Resizable context panel — drag the left edge
  const handleResizeMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = contextWidth;
      const onMove = (ev: MouseEvent) => {
        const delta = startX - ev.clientX;
        setContextWidth(Math.max(260, Math.min(720, startWidth + delta)));
      };
      const onUp = () => {
        isDragging.current = false;
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
      };
      isDragging.current = true;
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    },
    [contextWidth],
  );

  // Auto-scroll
  const { scrollContainerRef, bottomRef, showScrollFab, scrollToBottom, handleScroll } =
    useAutoScroll([events.length, streamingContent]);

  // Playbook autocomplete
  const playbookMatch = useMemo(() => {
    if (!inputValue.startsWith("/")) return null;
    const firstSpaceIdx = inputValue.indexOf(" ");
    if (firstSpaceIdx !== -1) return null;
    return inputValue.slice(1);
  }, [inputValue]);

  const handleSend = useCallback(() => {
    const text = inputValue.trim();
    if (!text) return;
    const sent = sendUserAction({
      action: "message",
      args: { content: text },
    });
    if (!sent) {
      toast.error("Not connected — waiting for backend...");
      return;
    }
    setInputValue("");
  }, [inputValue]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleStop = () => {
    sendUserAction({ action: "change_agent_state", args: { agent_state: "stopped" } });
  };

  const handleResume = () => {
    sendUserAction({ action: "change_agent_state", args: { agent_state: "running" } });
  };

  // Override state display when the agent appears stuck
  const stateInfo = runningTimedOut
    ? { label: "May be stuck", color: "text-orange-500", pulse: false }
    : runningSlow && effectiveAgentState === AgentState.RUNNING
      ? { label: "Still working...", color: "text-yellow-500", pulse: true }
      : agentStateDisplay(effectiveAgentState);
  const canSend =
    isConnected &&
    (
      effectiveAgentState === AgentState.AWAITING_USER_INPUT ||
      effectiveAgentState === AgentState.PAUSED ||
      effectiveAgentState === AgentState.ERROR ||
      effectiveAgentState === AgentState.FINISHED ||
      effectiveAgentState === AgentState.STOPPED ||
      effectiveAgentState === AgentState.RATE_LIMITED ||
      runningTimedOut
    );
  const isRunning = effectiveAgentState === AgentState.RUNNING && !runningTimedOut;
  const isEmpty = events.length === 0 && !streamingContent;
  const needsSetup = !apiKeySet || !modelSet;

  return (
    <div className="flex h-full flex-col">
      {/* Chat TopBar */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b bg-background/80 backdrop-blur-sm px-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="h-8 w-8" asChild>
            <Link to="/"><ArrowLeft className="h-4 w-4" /></Link>
          </Button>
          <div className="flex items-center gap-2 min-w-0">
            <MessageSquare className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <span className="truncate font-medium text-sm max-w-75">
              {conversation?.title || "New Conversation"}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Agent State Pill */}
          <div className={cn(
            "flex items-center gap-1.5 rounded-full border px-2.5 py-1",
            effectiveAgentState === AgentState.ERROR
              ? "border-destructive/30 bg-destructive/5"
              : runningTimedOut
                ? "border-orange-500/30 bg-orange-500/5"
                : effectiveAgentState === AgentState.RUNNING
                  ? "border-green-500/30 bg-green-500/5"
                  : "border-border",
          )}>
            {effectiveAgentState === AgentState.LOADING ? (
              <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
            ) : (
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  stateInfo.color.replace("text-", "bg-"),
                  stateInfo.pulse && "animate-pulse",
                )}
              />
            )}
            <span className={cn("text-[11px] font-medium", stateInfo.color)}>
              {stateInfo.label}
            </span>
          </div>

          {/* Connection indicator */}
          {(!isConnected || isReconnecting) && (
            <>
              <Separator orientation="vertical" className="h-4" />
              <div className="flex items-center gap-1.5">
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    isReconnecting
                      ? "bg-yellow-500 animate-pulse"
                      : "bg-red-500",
                  )}
                />
                <span className={cn(
                  "text-[10px]",
                  isReconnecting ? "text-yellow-500" : "text-red-500",
                )}>
                  {isReconnecting ? "Reconnecting..." : "Disconnected"}
                </span>
              </div>
            </>
          )}

          {isRunning && (
            <Button variant="destructive" size="sm" className="h-7 text-xs" onClick={handleStop}>
              <Square className="mr-1 h-3 w-3" /> Stop
            </Button>
          )}
          {runningTimedOut && (
            <Button variant="outline" size="sm" className="h-7 text-xs border-orange-500/30 text-orange-500 hover:bg-orange-500/10" onClick={handleResume}>
              <RotateCcw className="mr-1 h-3 w-3" /> Retry
            </Button>
          )}
          {(effectiveAgentState === AgentState.PAUSED ||
            effectiveAgentState === AgentState.STOPPED) && (
            <Button variant="outline" size="sm" className="h-7 text-xs" onClick={handleResume}>
              <Play className="mr-1 h-3 w-3" /> Resume
            </Button>
          )}

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            title="Toggle context panel"
            onClick={() => setContextPanelOpen(!contextPanelOpen)}
          >
            {contextPanelOpen ? (
              <PanelRightClose className="h-4 w-4" />
            ) : (
              <PanelRightOpen className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      {/* Chat Body */}
      <div className="flex flex-1 overflow-hidden">
        {/* Main Chat Column */}
        <div className="relative flex flex-1 flex-col min-w-0">
          {/* Tasks strip — shown at top when tasks exist */}
          <InlineTasksPanel />

          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto"
          >
            <div className="mx-auto flex max-w-2xl flex-col gap-3 p-4">
              {/* Setup banner — shown when API key or model is missing */}
              {needsSetup && isEmpty && <SetupBanner apiKeySet={apiKeySet} modelSet={modelSet} />}

              {/* Welcome empty state */}
              {isEmpty && !isRunning && effectiveAgentState !== AgentState.LOADING && (
                <WelcomeState />
              )}

              {/* Loading state — only first few seconds */}
              {isEmpty && effectiveAgentState === AgentState.LOADING && (
                <div className="mx-auto flex flex-col items-center gap-3 py-16 text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">Connecting to agent...</p>
                </div>
              )}

              {groupedEvents.map((item, i) => {
                if (item.type === "single") {
                  return <EventCard key={item.event.id != null ? `e-${item.event.id}` : `i-${i}`} event={item.event} />;
                } else {
                  return (
                    <AgentWorkflowGroup 
                      key={`wf-${item.id || i}`} 
                      events={item.events} 
                      isLatest={i === groupedEvents.length - 1} 
                    />
                  );
                }
              })}

              {/* Streaming indicator */}
              {streamingContent && <StreamingBubble content={streamingContent} />}

              {isRunning && !streamingContent && events.length > 0 && (
                <div className="flex items-center gap-2 text-muted-foreground text-sm py-1">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  <span className="text-xs">
                    {runningSlow ? "Taking longer than expected..." : "Working..."}
                  </span>
                </div>
              )}

              {runningTimedOut && events.length > 0 && (
                <div className="flex items-center gap-3 rounded-lg border border-orange-500/30 bg-orange-500/5 px-3 py-2 text-sm">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-orange-500" />
                  <span className="text-xs text-muted-foreground">
                    The agent hasn't responded in a while. You can send a message, retry, or stop it.
                  </span>
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          {showScrollFab && (
            <button
              type="button"
              onClick={() => scrollToBottom()}
              aria-label="Scroll to bottom"
              className="absolute bottom-24 right-6 z-10 flex h-8 w-8 items-center justify-center rounded-full border bg-background shadow-md hover:bg-accent transition-colors"
            >
              <ArrowDown className="h-3.5 w-3.5" />
            </button>
          )}

          {effectiveAgentState === AgentState.AWAITING_USER_CONFIRMATION && (
            <ConfirmationBanner events={events} />
          )}

          {/* Input Bar */}
          <div className="border-t bg-background/80 backdrop-blur-sm p-3">
            <div className="relative mx-auto flex max-w-2xl items-end gap-2">
              {playbookMatch !== null && playbooks.length > 0 && (
                <PlaybookAutocomplete
                  playbooks={playbooks}
                  filter={playbookMatch}
                  onSelect={(pb) => setInputValue(`/${pb.name} `)}
                />
              )}

              <Textarea
                placeholder={
                  !isConnected
                    ? "Establishing secure uplink..."
                    : needsSetup
                      ? "Awaiting API telemetry configuration..."
                      : canSend
                        ? "Provide directive... (/ for playbooks)"
                        : "Agent sequence active..."
                }
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={!canSend}
                className="min-h-10 max-h-37.5 resize-none rounded-xl border-muted-foreground/20 bg-muted/30 text-sm"
                rows={1}
              />
              <Button
                size="icon"
                className="h-9 w-9 rounded-xl shrink-0"
                onClick={handleSend}
                disabled={!canSend || !inputValue.trim()}
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Resizable Context Panel */}
        {contextPanelOpen && (
          <div ref={contextPanelRef} className="flex shrink-0 border-l">
            {/* Drag handle */}
            <div
              className="w-1 shrink-0 cursor-col-resize hover:bg-primary/40 active:bg-primary/60 transition-colors"
              onMouseDown={handleResizeMouseDown}
            />
            <div className="flex-1 min-w-0 overflow-hidden">
              <ContextPanel />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
