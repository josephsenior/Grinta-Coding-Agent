import { useCallback, useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import {
  ArrowLeft,
  Send,
  Square,
  Play,
  Loader2,
  PanelRightOpen,
  PanelRightClose,
  PanelLeftOpen,
  PanelLeftClose,
  ArrowDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { useConversation } from "@/hooks/use-conversations";
import { usePlaybooks } from "@/hooks/use-playbooks";
import { useSocket } from "@/hooks/use-socket";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useSessionStore } from "@/stores/session-store";
import { useAppStore } from "@/stores/app-store";
import { sendUserAction } from "@/socket/client";
import { AgentState } from "@/types/agent";
import { EventCard } from "@/components/chat/EventRenderer";
import { StreamingBubble } from "@/components/chat/StreamingBubble";
import { ConfirmationBanner } from "@/components/chat/ConfirmationBanner";
import { PlaybookAutocomplete } from "@/components/chat/PlaybookAutocomplete";
import { ContextPanel } from "@/components/context-panel/ContextPanel";
import { SidePanel } from "@/components/side-panel/SidePanel";
import { cn } from "@/lib/utils";

function agentStateDisplay(state: AgentState) {
  switch (state) {
    case AgentState.LOADING:
      return { label: "Initializing...", color: "text-muted-foreground", pulse: true };
    case AgentState.RUNNING:
      return { label: "Agent working...", color: "text-green-500", pulse: true };
    case AgentState.AWAITING_USER_INPUT:
      return { label: "Your turn", color: "text-blue-500", pulse: false };
    case AgentState.PAUSED:
      return { label: "Paused", color: "text-yellow-500", pulse: false };
    case AgentState.STOPPED:
      return { label: "Stopped", color: "text-muted-foreground", pulse: false };
    case AgentState.FINISHED:
      return { label: "Task complete", color: "text-green-500", pulse: false };
    case AgentState.ERROR:
      return { label: "Error occurred", color: "text-destructive", pulse: false };
    case AgentState.AWAITING_USER_CONFIRMATION:
      return { label: "Needs approval", color: "text-orange-500", pulse: true };
    case AgentState.RATE_LIMITED:
      return { label: "Rate limited", color: "text-yellow-500", pulse: false };
    default:
      return { label: state, color: "text-muted-foreground", pulse: false };
  }
}

export default function Chat() {
  const { id } = useParams<{ id: string }>();
  const { data: conversation } = useConversation(id);
  const { data: playbooks = [] } = usePlaybooks(id);

  // Socket lifecycle
  useSocket(id);

  const events = useSessionStore((s) => s.events);
  const agentState = useSessionStore((s) => s.agentState);
  const streamingContent = useSessionStore((s) => s.streamingContent);
  const isConnected = useSessionStore((s) => s.isConnected);
  const isReconnecting = useSessionStore((s) => s.isReconnecting);
  const contextPanelOpen = useAppStore((s) => s.contextPanelOpen);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);

  const [inputValue, setInputValue] = useState("");

  // Auto-scroll
  const { scrollContainerRef, bottomRef, showScrollFab, scrollToBottom, handleScroll } =
    useAutoScroll([events.length, streamingContent]);

  // Playbook autocomplete
  const playbookMatch = useMemo(() => {
    if (!inputValue.startsWith("/")) return null;
    // Only show autocomplete if the first word starts with /
    const firstSpaceIdx = inputValue.indexOf(" ");
    if (firstSpaceIdx !== -1) return null;
    return inputValue.slice(1); // the filter string after /
  }, [inputValue]);

  const handleSend = useCallback(() => {
    const text = inputValue.trim();
    if (!text) return;
    sendUserAction({
      action: "message",
      args: { content: text },
    });
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

  const stateInfo = agentStateDisplay(agentState);
  const canSend =
    agentState === AgentState.AWAITING_USER_INPUT ||
    agentState === AgentState.PAUSED ||
    agentState === AgentState.ERROR ||
    agentState === AgentState.FINISHED ||
    agentState === AgentState.STOPPED;
  const isRunning = agentState === AgentState.RUNNING;

  return (
    <div className="flex h-full flex-col">
      {/* Chat TopBar */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild>
            <Link to="/"><ArrowLeft className="h-4 w-4" /></Link>
          </Button>
          <span className="truncate font-medium text-sm max-w-[300px]">
            {conversation?.title || "Loading..."}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Agent State */}
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                stateInfo.color.replace("text-", "bg-"),
                stateInfo.pulse && "animate-pulse",
              )}
            />
            <span className={cn("text-xs font-medium", stateInfo.color)}>
              {stateInfo.label}
            </span>
          </div>

          <Separator orientation="vertical" className="h-5" />

          {/* Connection indicator */}
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                isReconnecting
                  ? "bg-yellow-500 animate-pulse"
                  : isConnected
                    ? "bg-green-500"
                    : "bg-red-500",
              )}
            />
            {isReconnecting && (
              <span className="text-[10px] text-yellow-500">Reconnecting...</span>
            )}
          </div>

          {isRunning && (
            <Button variant="destructive" size="sm" onClick={handleStop}>
              <Square className="mr-1 h-3 w-3" /> Stop
            </Button>
          )}
          {(agentState === AgentState.PAUSED || agentState === AgentState.STOPPED) && (
            <Button variant="outline" size="sm" onClick={handleResume}>
              <Play className="mr-1 h-3 w-3" /> Resume
            </Button>
          )}

          <Button
            variant="ghost"
            size="icon"
            title="Toggle side panel"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-4 w-4" />
            ) : (
              <PanelLeftOpen className="h-4 w-4" />
            )}
          </Button>

          <Button
            variant="ghost"
            size="icon"
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
        {/* Side Panel */}
        {sidebarOpen && (
          <div className="w-64 shrink-0 border-r">
            <SidePanel conversationId={id ?? ""} />
          </div>
        )}
        {/* Event Stream */}
        <div className="relative flex flex-1 flex-col">
          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto p-4"
          >
            <div className="mx-auto flex max-w-3xl flex-col gap-3">
              {events.map((event, i) => (
                <EventCard key={event.id ?? i} event={event} />
              ))}

              {/* Streaming indicator */}
              {streamingContent && <StreamingBubble content={streamingContent} />}

              {/* Loading state */}
              {isRunning && !streamingContent && (
                <div className="flex items-center gap-2 text-muted-foreground text-sm">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Agent is working...
                </div>
              )}

              <div ref={bottomRef} />
            </div>
          </div>

          {/* Jump to bottom FAB */}
          {showScrollFab && (
            <button
              type="button"
              onClick={() => scrollToBottom()}
              className="absolute bottom-24 right-6 z-10 flex h-9 w-9 items-center justify-center rounded-full border bg-background shadow-lg hover:bg-accent transition-colors"
            >
              <ArrowDown className="h-4 w-4" />
            </button>
          )}

          {/* Confirmation Banner */}
          {agentState === AgentState.AWAITING_USER_CONFIRMATION && (
            <ConfirmationBanner events={events} />
          )}

          {/* Input Bar */}
          <div className="border-t p-4">
            <div className="relative mx-auto flex max-w-3xl items-end gap-2">
              {/* Playbook autocomplete dropdown */}
              {playbookMatch !== null && playbooks.length > 0 && (
                <PlaybookAutocomplete
                  playbooks={playbooks}
                  filter={playbookMatch}
                  onSelect={(pb) => setInputValue(`/${pb.name} `)}
                />
              )}

              <Textarea
                placeholder={canSend ? "Type a message... (/ for playbooks)" : "Agent is working..."}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={!canSend}
                className="min-h-[40px] max-h-[150px] resize-none"
                rows={1}
              />
              <Button
                size="icon"
                onClick={handleSend}
                disabled={!canSend || !inputValue.trim()}
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Context Panel */}
        {contextPanelOpen && (
          <div className="w-[420px] shrink-0 border-l">
            <ContextPanel />
          </div>
        )}
      </div>
    </div>
  );
}
