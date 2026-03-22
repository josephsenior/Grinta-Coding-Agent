import {
  useCallback,
  useState,
  useMemo,
  useEffect,
  useLayoutEffect,
  useRef,
} from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Send,
  Square,
  Play,
  Loader2,
  PanelLeft,
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
  RotateCcw,
  Paperclip,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useConversation } from "@/hooks/use-conversations";
import { usePlaybooks } from "@/hooks/use-playbooks";
import { useSocket } from "@/hooks/use-socket";
import { useRecoverChatAfterConnectivity } from "@/hooks/use-recover-chat-after-connectivity";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { useSessionStore } from "@/stores/session-store";
import { useAppStore } from "@/stores/app-store";
import { sendUserAction } from "@/socket/client";
import { toast } from "sonner";
import { AgentState, ActionType } from "@/types/agent";
import type { ActionEvent } from "@/types/events";
import { EventCard } from "@/components/chat/EventRenderer";
import { StreamingBubble } from "@/components/chat/StreamingBubble";
import { DraftWelcomeIllustration } from "@/components/chat/DraftWelcomeIllustration";
import { ConfirmationBanner } from "@/components/chat/ConfirmationBanner";
import { PlaybookAutocomplete } from "@/components/chat/PlaybookAutocomplete";
import { getSettings } from "@/api/settings";
import { createConversation } from "@/api/conversations";
import { uploadFiles, agentPathFromUploadResponse } from "@/api/files";
import {
  setDraftChatBootstrap,
  takeDraftChatBootstrap,
} from "@/lib/draft-chat-bootstrap";
import { cn } from "@/lib/utils";
import {
  AGENT_RUNNING_STALE_UI_MS,
  SUSTAINED_DISCONNECT_NOTICE_MS,
} from "@/lib/constants";
import { deriveLiveActivity, lifecycleDisplay } from "@/lib/agent-activity";

/** Workspace uploads: text/code only (server stores as UTF-8). Images use image_urls (data URLs), not this path. */
const CHAT_ATTACH_MAX_FILES = 8;
const CHAT_ATTACH_MAX_BYTES = 12 * 1024 * 1024;
const CHAT_IMAGE_MAX_COUNT = 4;
const CHAT_IMAGE_MAX_BYTES = 8 * 1024 * 1024;
const CHAT_ATTACH_ACCEPT = [
  ".txt",
  ".md",
  ".markdown",
  ".json",
  ".csv",
  ".xml",
  ".yaml",
  ".yml",
  ".py",
  ".ts",
  ".tsx",
  ".js",
  ".jsx",
  ".mjs",
  ".cjs",
  ".html",
  ".htm",
  ".css",
  ".scss",
  ".less",
  ".rs",
  ".go",
  ".java",
  ".kt",
  ".cs",
  ".php",
  ".rb",
  ".swift",
  ".sql",
  ".sh",
  ".bash",
  ".ps1",
  ".zsh",
  ".toml",
  ".ini",
  ".cfg",
  ".log",
].join(",");
const CHAT_IMAGE_ACCEPT = "image/jpeg,image/png,image/gif,image/webp";
const CHAT_FILE_INPUT_ACCEPT = `${CHAT_ATTACH_ACCEPT},${CHAT_IMAGE_ACCEPT}`;

function isImageFile(file: File): boolean {
  return file.type.startsWith("image/");
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error ?? new Error("read failed"));
    r.readAsDataURL(file);
  });
}

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
    <div className="shrink-0 border-b border-border/40 bg-muted/10">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted/35"
      >
        <CheckSquare className="h-3 w-3 shrink-0 opacity-60" />
        <span className="font-normal tracking-wide text-muted-foreground/90">Tasks</span>
        <span className="tabular-nums text-muted-foreground/75">
          {doneTasks}/{tasks.length}
          {activeTasks > 0 ? ` · ${activeTasks} in progress` : ""}
        </span>
        <span className="ml-auto text-muted-foreground/60">
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </span>
      </button>
      {expanded && (
        <div className="max-h-40 overflow-y-auto px-4 pb-2">
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}
        </div>
      )}
    </div>
  );
}

// --- Setup banner for missing configuration ---
function SetupBanner({ apiKeySet, modelSet }: { apiKeySet: boolean; modelSet: boolean }) {
  const setSettingsWindowOpen = useAppStore((s) => s.setSettingsWindowOpen);
  if (apiKeySet && modelSet) return null;

  return (
    <div className="mx-auto w-full max-w-xl">
      <div className="rounded-2xl border border-amber-500/25 bg-amber-500/3 p-4 dark:border-amber-500/20 dark:bg-amber-500/4">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-amber-500/20 bg-transparent dark:border-amber-500/15">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400/90" />
          </div>
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="text-[13px] font-medium text-foreground">Finish setup</p>
            <p className="text-[12px] leading-relaxed text-muted-foreground">
              {!modelSet && !apiKeySet
                ? "Add an API key and pick a model in Settings to run the agent."
                : !apiKeySet
                  ? "Add your API key in Settings so the agent can call the model."
                  : "Choose a model in Settings."}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-1 h-8 gap-1.5 border-border/60 text-xs shadow-none"
              onClick={() => setSettingsWindowOpen(true)}
            >
              <Settings className="h-3 w-3 opacity-70" />
              Open Settings
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Live connection banner (after at least one successful connect) ---
function ConnectionBanner({
  isConnected,
  isReconnecting,
  everConnected,
  showSustainedOffline,
}: {
  isConnected: boolean;
  isReconnecting: boolean;
  everConnected: boolean;
  /** Red "lost" strip only after offline long enough (brief blips stay clean). */
  showSustainedOffline: boolean;
}) {
  if (isConnected || !everConnected) return null;

  if (!isReconnecting && !showSustainedOffline) return null;

  return (
    <div
      className={cn(
        "shrink-0 border-b px-4 py-2.5 text-center text-[12px] leading-relaxed",
        isReconnecting
          ? "border-amber-500/30 bg-amber-500/6 text-amber-950 dark:border-amber-500/25 dark:bg-amber-500/5 dark:text-amber-100/90"
          : "border-destructive/35 bg-destructive/6 text-destructive dark:border-destructive/30 dark:bg-destructive/5 dark:text-red-200/85",
      )}
    >
      {isReconnecting ? (
        <p>
          <span className="font-medium">Reconnecting…</span>{" "}
          <span className="opacity-90">
            Restoring the live link. You can keep reading; sending will work again shortly.
          </span>
        </p>
      ) : (
        <div className="flex flex-col items-center gap-2 sm:flex-row sm:justify-center sm:gap-3">
          <p className="max-w-xl">
            <span className="font-medium">Connection lost.</span> Messages can&apos;t be sent until the
            link is back. Auto-retry has stopped — refresh the page after checking the backend.
          </p>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="h-8 shrink-0 text-xs"
            onClick={() => window.location.reload()}
          >
            Refresh page
          </Button>
        </div>
      )}
    </div>
  );
}

function ConversationErrorBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mx-auto w-full max-w-xl px-4 pt-4">
      <div className="rounded-2xl bg-destructive/8 p-4 ring-1 ring-destructive/15">
        <div className="flex flex-col gap-2 text-left sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 space-y-1">
            <p className="text-[13px] font-medium text-foreground">Couldn&apos;t load this conversation</p>
            <p className="text-[12px] leading-relaxed text-muted-foreground">
              The API may be down or this chat no longer exists. Check that the Forge backend is running,
              then try again.
            </p>
          </div>
          <Button variant="outline" size="sm" className="h-8 shrink-0 text-xs" onClick={onRetry}>
            Try again
          </Button>
        </div>
      </div>
    </div>
  );
}

// --- Welcome empty state (minimal SVG; connecting keeps a single status line) ---
function WelcomeState({ waitingForConnection }: { waitingForConnection?: boolean }) {
  return (
    <div
      className="mx-auto flex max-w-md flex-col items-center justify-center gap-5 py-16"
      role="status"
      aria-label={waitingForConnection ? "Connecting to server" : "New chat"}
    >
      <DraftWelcomeIllustration className="w-[min(220px,72vw)] text-primary/30 dark:text-primary/22" />
      {waitingForConnection ? (
        <p className="text-[12px] text-muted-foreground">Connecting…</p>
      ) : null}
    </div>
  );
}

export default function Chat() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isDraft = id === "new";

  /** Blocks duplicate POST /conversations while a draft chat is being created (navigation may lag after await). */
  const draftCreateInFlightRef = useRef(false);
  const [isDraftCreatePending, setIsDraftCreatePending] = useState(false);

  useLayoutEffect(() => {
    if (id && id !== "new") {
      draftCreateInFlightRef.current = false;
      setIsDraftCreatePending(false);
    }
  }, [id]);

  const {
    data: conversation,
    isError: conversationQueryError,
    refetch: refetchConversation,
  } = useConversation(id);
  const { data: playbooks = [] } = usePlaybooks(id);

  useSocket(isDraft ? undefined : id);
  useRecoverChatAfterConnectivity(isDraft ? undefined : id);

  useEffect(() => {
    if (!isDraft) return;
    const { clearSession } = useSessionStore.getState();
    clearSession();
    useSessionStore.setState({ agentState: AgentState.AWAITING_USER_INPUT });
  }, [isDraft, id]);

  const [everConnected, setEverConnected] = useState(false);
  useEffect(() => {
    setEverConnected(false);
  }, [id]);

  const events = useSessionStore((s) => s.events);

  const agentState = useSessionStore((s) => s.agentState);
  const streamingContent = useSessionStore((s) => s.streamingContent);
  const isConnected = useSessionStore((s) => s.isConnected);
  const isReconnecting = useSessionStore((s) => s.isReconnecting);
  useEffect(() => {
    if (isConnected) setEverConnected(true);
  }, [isConnected]);

  const [showSustainedOffline, setShowSustainedOffline] = useState(false);
  useEffect(() => {
    if (isConnected || isReconnecting || !everConnected) {
      setShowSustainedOffline(false);
      return;
    }
    const t = setTimeout(() => setShowSustainedOffline(true), SUSTAINED_DISCONNECT_NOTICE_MS);
    return () => clearTimeout(t);
  }, [isConnected, isReconnecting, everConnected]);

  const contextPanelOpen = useAppStore((s) => s.contextPanelOpen);
  const setContextPanelOpen = useAppStore((s) => s.setContextPanelOpen);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);

  const [inputValue, setInputValue] = useState("");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setPendingFiles([]);
  }, [id]);

  // Fetch settings to know if the API key / model are configured
  const { data: settings, isLoading: settingsLoading } = useQuery({
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

  // If agentState is RUNNING for a while with no new events or streaming, offer retry/stop (UI-only; see AGENT_RUNNING_STALE_UI_MS).
  const [runningTimedOut, setRunningTimedOut] = useState(false);
  useEffect(() => {
    if (AGENT_RUNNING_STALE_UI_MS <= 0) {
      setRunningTimedOut(false);
      return;
    }
    if (agentState !== AgentState.RUNNING) {
      setRunningTimedOut(false);
      return;
    }
    const timer = setTimeout(() => setRunningTimedOut(true), AGENT_RUNNING_STALE_UI_MS);
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

  const effectiveAgentStateForUi = isDraft
    ? AgentState.AWAITING_USER_INPUT
    : effectiveAgentState;

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

  const addPendingFiles = useCallback((list: FileList | File[]) => {
    const incoming = Array.from(list);
    if (incoming.length === 0) return;

    setPendingFiles((prev) => {
      const next = [...prev];
      for (const file of incoming) {
        const image = isImageFile(file);
        const maxBytes = image ? CHAT_IMAGE_MAX_BYTES : CHAT_ATTACH_MAX_BYTES;
        if (file.size > maxBytes) {
          toast.error(`"${file.name}" is too large`, {
            description: `Max ${Math.round(maxBytes / (1024 * 1024))} MB per ${image ? "image" : "file"}.`,
          });
          continue;
        }
        const imagesNow = next.filter(isImageFile).length;
        if (image && imagesNow >= CHAT_IMAGE_MAX_COUNT) {
          toast.error(`At most ${CHAT_IMAGE_MAX_COUNT} images per message.`);
          continue;
        }
        if (next.length >= CHAT_ATTACH_MAX_FILES) {
          toast.error(`At most ${CHAT_ATTACH_MAX_FILES} attachments per message.`);
          break;
        }
        next.push(file);
      }
      return next;
    });
  }, []);

  const handleSend = useCallback(async () => {
    const text = inputValue.trim();
    const files = pendingFiles;
    if (!text && files.length === 0) return;
    if (!id) {
      toast.error("No conversation", { description: "Open or create a chat first." });
      return;
    }

    const imageFiles = files.filter(isImageFile);
    const workspaceFiles = files.filter((f) => !isImageFile(f));

    if (imageFiles.length > 0) {
      if (settingsLoading) {
        toast.info("Checking your model…", {
          description: "Wait a moment before sending images.",
        });
        return;
      }
      if (!settings?.llm_model_supports_vision) {
        toast.error("This model can't view images", {
          description:
            "Pick a vision-capable model in Settings, or remove the images and send only text or workspace files.",
        });
        return;
      }
    }

    setIsUploading(true);
    try {
      if (isDraft) {
        if (draftCreateInFlightRef.current) {
          return;
        }
        draftCreateInFlightRef.current = true;
        setIsDraftCreatePending(true);
        try {
          let imageUrls: string[] = [];
          if (imageFiles.length > 0) {
            imageUrls = await Promise.all(imageFiles.map(readFileAsDataUrl));
          }

          if (workspaceFiles.length > 0) {
            const res = await createConversation({});
            const cid = res.conversation_id;
            if (!cid) {
              draftCreateInFlightRef.current = false;
              setIsDraftCreatePending(false);
              toast.error("Could not start chat", {
                description: "The server did not return a conversation id. Try again.",
              });
              return;
            }
            const body =
              text ||
              (imageUrls.length > 0 ? "Please see the attached image(s)." : "(Attached files)");
            setDraftChatBootstrap({
              conversationId: cid,
              text: body,
              workspaceFiles,
              imageUrls,
            });
            navigate(`/chat/${cid}`, { replace: true });
            setInputValue("");
            setPendingFiles([]);
            return;
          }

          const initialMsg =
            text || (imageUrls.length > 0 ? "Please see the attached image(s)." : undefined);
          if (!initialMsg) {
            draftCreateInFlightRef.current = false;
            setIsDraftCreatePending(false);
            toast.error("Message required", {
              description: "Type something or attach an image to start.",
            });
            return;
          }

          const res = await createConversation({
            initial_user_msg: initialMsg,
            image_urls: imageUrls.length > 0 ? imageUrls : undefined,
          });
          const newId = res.conversation_id;
          if (!newId) {
            draftCreateInFlightRef.current = false;
            setIsDraftCreatePending(false);
            toast.error("Could not start chat", {
              description: "The server did not return a conversation id. Try again.",
            });
            return;
          }
          navigate(`/chat/${newId}`, { replace: true });
          setInputValue("");
          setPendingFiles([]);
          return;
        } catch (draftErr) {
          draftCreateInFlightRef.current = false;
          setIsDraftCreatePending(false);
          throw draftErr;
        }
      }

      let fileUrls: string[] = [];
      let imageUrls: string[] = [];
      if (workspaceFiles.length > 0) {
        const { uploaded_files: uploaded, skipped_files: skipped } = await uploadFiles(
          id,
          workspaceFiles,
        );
        for (const s of skipped) {
          toast.error(`Skipped “${s.name}”`, { description: s.reason });
        }
        fileUrls = uploaded.map(agentPathFromUploadResponse);
        if (workspaceFiles.length > 0 && fileUrls.length === 0) {
          toast.error("Upload failed", {
            description: "No files were written to the workspace. Check the server log.",
          });
          return;
        }
      }

      if (imageFiles.length > 0) {
        imageUrls = await Promise.all(imageFiles.map(readFileAsDataUrl));
      }

      const args: Record<string, unknown> = {
        content: text,
      };
      if (fileUrls.length > 0) {
        args.file_urls = fileUrls;
      }
      if (imageUrls.length > 0) {
        args.image_urls = imageUrls;
      }

      const sent = sendUserAction({
        action: "message",
        args,
      });
      if (!sent) {
        toast.error("Not connected", {
          description: everConnected
            ? "Wait for reconnect or refresh the page. Ensure the Forge backend is running."
            : "Still connecting… If this persists, start the API and refresh.",
        });
        return;
      }
      setInputValue("");
      setPendingFiles([]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Upload failed";
      toast.error("Could not send message", { description: msg });
    } finally {
      setIsUploading(false);
    }
  }, [
    inputValue,
    pendingFiles,
    id,
    everConnected,
    settings?.llm_model_supports_vision,
    settingsLoading,
    isDraft,
    navigate,
  ]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleStop = () => {
    sendUserAction({ action: "change_agent_state", args: { agent_state: "stopped" } });
  };

  const handleResume = () => {
    sendUserAction({ action: "change_agent_state", args: { agent_state: "running" } });
  };

  const baseLifecycle = lifecycleDisplay(effectiveAgentStateForUi);
  const stateInfo = runningTimedOut
    ? {
        label: "May need attention",
        textClass: "text-orange-600 dark:text-orange-400",
        dotClass: "bg-orange-500 dark:bg-orange-400",
        pulse: false,
      }
    : baseLifecycle;

  const needsSetup = !apiKeySet || !modelSet;

  const canSend =
    (isDraft && !needsSetup && !isUploading && !isDraftCreatePending) ||
    (isConnected &&
      (effectiveAgentStateForUi === AgentState.AWAITING_USER_INPUT ||
        effectiveAgentStateForUi === AgentState.PAUSED ||
        effectiveAgentStateForUi === AgentState.ERROR ||
        effectiveAgentStateForUi === AgentState.FINISHED ||
        effectiveAgentStateForUi === AgentState.STOPPED ||
        effectiveAgentStateForUi === AgentState.RATE_LIMITED ||
        runningTimedOut));
  const isRunning =
    !isDraft && effectiveAgentStateForUi === AgentState.RUNNING && !runningTimedOut;
  const isEmpty = events.length === 0 && !streamingContent;
  /** Paperclip: draft chat has no socket yet; workspace files use bootstrap after first create. */
  const canOpenFilePicker =
    (isDraft && !needsSetup && !isUploading && !isDraftCreatePending) ||
    (isConnected && !!id && id !== "new" && !needsSetup && !isUploading);

  const liveActivity = useMemo(() => {
    const streaming = !!streamingContent;
    return deriveLiveActivity(events, {
      streaming,
      isRunning: isRunning || streaming,
    });
  }, [events, streamingContent, isRunning]);

  const showActivityStrip = !!liveActivity && (isRunning || !!streamingContent);

  useEffect(() => {
    if (isDraft || !id || id === "new" || !isConnected) return;
    const boot = takeDraftChatBootstrap(id);
    if (!boot) return;
    void (async () => {
      try {
        let fileUrls: string[] = [];
        if (boot.workspaceFiles.length > 0) {
          const { uploaded_files: uploaded, skipped_files: skipped } = await uploadFiles(
            id,
            boot.workspaceFiles,
          );
          for (const s of skipped) {
            toast.error(`Skipped “${s.name}”`, { description: s.reason });
          }
          fileUrls = uploaded.map(agentPathFromUploadResponse);
          if (boot.workspaceFiles.length > 0 && fileUrls.length === 0) {
            toast.error("Upload failed", {
              description: "No files were written to the workspace. Check the server log.",
            });
            return;
          }
        }
        const args: Record<string, unknown> = { content: boot.text };
        if (fileUrls.length > 0) args.file_urls = fileUrls;
        if (boot.imageUrls.length > 0) args.image_urls = boot.imageUrls;
        const sent = sendUserAction({ action: "message", args });
        if (!sent) {
          toast.error("Could not send attachments", {
            description: "Connection dropped. Refresh and try again.",
          });
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Send failed";
        toast.error("Could not send message with attachments", { description: msg });
      }
    })();
  }, [id, isConnected, isDraft]);

  return (
    <div className="flex h-full flex-col">
      {/* Chat TopBar */}
      <div className="flex min-h-12 shrink-0 items-center justify-between gap-3 border-b border-border/40 bg-card/85 px-4 py-1.5 backdrop-blur-sm dark:bg-card/75">
        <div className="flex min-w-0 items-center gap-2 sm:gap-3">
          {!sidebarOpen && (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0"
                  onClick={() => setSidebarOpen(true)}
                  aria-label="Show conversation list"
                >
                  <PanelLeft className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Show conversation list</TooltipContent>
            </Tooltip>
          )}
          <div className="flex min-w-0 items-center gap-2">
            <MessageSquare className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="max-w-75 truncate text-sm font-medium">
              {isDraft ? "New chat" : conversation?.title || "Conversation"}
            </span>
          </div>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center sm:gap-2">
          {showActivityStrip && liveActivity && (
            <div
              className="flex max-w-[min(100vw-8rem,18rem)] items-center gap-1.5 text-[11px] text-foreground/90 sm:max-w-[20rem]"
              title={
                liveActivity.detail
                  ? `${liveActivity.verb} · ${liveActivity.detail}`
                  : liveActivity.verb
              }
            >
              <liveActivity.Icon
                className={cn(
                  "h-3.5 w-3.5 shrink-0 opacity-90",
                  liveActivity.verb === "Working…" && "animate-spin",
                )}
              />
              <span className="shrink-0 font-medium">{liveActivity.verb}</span>
              {liveActivity.detail && (
                <span className="min-w-0 truncate text-muted-foreground">
                  · {liveActivity.detail}
                </span>
              )}
              {liveActivity.linesAdded != null && liveActivity.linesAdded > 0 && (
                <span className="shrink-0 tabular-nums text-emerald-600 dark:text-emerald-400">
                  +{liveActivity.linesAdded}
                </span>
              )}
              {liveActivity.linesRemoved != null && liveActivity.linesRemoved > 0 && (
                <span className="shrink-0 tabular-nums text-red-500 dark:text-red-400">
                  −{liveActivity.linesRemoved}
                </span>
              )}
            </div>
          )}

          <div className="flex items-center gap-2">
            {/* Agent State Pill */}
            <div
              className={cn(
                "flex items-center gap-1.5 rounded-full px-2.5 py-1 ring-1 ring-border/35",
                effectiveAgentStateForUi === AgentState.ERROR
                  ? "bg-destructive/6 ring-destructive/20"
                  : runningTimedOut
                    ? "bg-orange-500/6 ring-orange-500/15"
                    : effectiveAgentStateForUi === AgentState.RUNNING
                      ? "bg-emerald-500/6 ring-emerald-500/15"
                      : "bg-muted/25",
              )}
            >
              {effectiveAgentStateForUi === AgentState.LOADING ? (
                <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
              ) : (
                <span
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    stateInfo.dotClass,
                    stateInfo.pulse && "animate-pulse",
                  )}
                />
              )}
              <span className={cn("text-[11px] font-medium", stateInfo.textClass)}>
                {stateInfo.label}
              </span>
            </div>

            {/* Connection indicator */}
            {!isDraft && (!isConnected || isReconnecting) && (
              <>
                <Separator orientation="vertical" className="h-4" />
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "h-1.5 w-1.5 rounded-full",
                      isReconnecting ? "animate-pulse bg-yellow-500" : "bg-red-500",
                    )}
                  />
                  <span
                    className={cn(
                      "text-[10px]",
                      isReconnecting ? "text-yellow-500" : "text-red-500",
                    )}
                  >
                    {isReconnecting ? "Reconnecting…" : "Disconnected"}
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
              <Button
                variant="outline"
                size="sm"
                className="h-7 border-orange-500/30 text-xs text-orange-500 hover:bg-orange-500/10"
                onClick={handleResume}
              >
                <RotateCcw className="mr-1 h-3 w-3" /> Retry
              </Button>
            )}
            {(effectiveAgentStateForUi === AgentState.PAUSED ||
              effectiveAgentStateForUi === AgentState.STOPPED) && (
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={handleResume}>
                <Play className="mr-1 h-3 w-3" /> Resume
              </Button>
            )}

            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              title="Toggle workspace panel"
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
      </div>

      {/* Chat Body — center column only; shell provides sidebar + workspace */}
      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
          {!isDraft && (
            <ConnectionBanner
              isConnected={isConnected}
              isReconnecting={isReconnecting}
              everConnected={everConnected}
              showSustainedOffline={showSustainedOffline}
            />
          )}
          {/* Tasks strip — shown at top when tasks exist */}
          <InlineTasksPanel />

          <div
            ref={scrollContainerRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto"
          >
            <div className="mx-auto flex max-w-[720px] flex-col gap-4 p-4 pb-8">
              {conversationQueryError && id && (
                <ConversationErrorBanner onRetry={() => void refetchConversation()} />
              )}

              {/* Setup banner — shown when API key or model is missing */}
              {needsSetup && isEmpty && <SetupBanner apiKeySet={apiKeySet} modelSet={modelSet} />}

              {/* Welcome empty state */}
              {isEmpty &&
                !isRunning &&
                effectiveAgentStateForUi !== AgentState.LOADING &&
                !conversationQueryError && (
                  <WelcomeState
                    waitingForConnection={
                      !isDraft && !isConnected && !everConnected && !!id && id !== "new"
                    }
                  />
                )}

              {/* Loading state — only first few seconds */}
              {isEmpty &&
                effectiveAgentStateForUi === AgentState.LOADING &&
                !conversationQueryError && (
                <div className="mx-auto flex max-w-sm flex-col items-center gap-3 py-16 text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">Connecting to agent…</p>
                  <p className="text-[11px] leading-relaxed text-muted-foreground/90">
                    If this never finishes, start the Forge backend and refresh. You can still read past
                    messages once they load from the server.
                  </p>
                </div>
              )}

              {events.map((event, i) => (
                <EventCard
                  key={event.id != null ? `e-${event.id}` : `i-${i}`}
                  event={event}
                />
              ))}

              {/* Streaming indicator */}
              {streamingContent && <StreamingBubble content={streamingContent} />}

              {runningTimedOut && events.length > 0 && (
                <div className="flex items-start gap-2.5 rounded-xl bg-orange-500/6 px-3 py-2.5 ring-1 ring-orange-500/12">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-orange-600/80 dark:text-orange-400/75" />
                  <span className="text-[12px] leading-relaxed text-muted-foreground">
                    No response for a while — you can message, retry, or stop.
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
              className="absolute bottom-24 right-6 z-10 flex h-8 w-8 items-center justify-center rounded-full bg-card/90 shadow-sm ring-1 ring-border/40 transition-colors hover:bg-muted/60"
            >
              <ArrowDown className="h-3.5 w-3.5" />
            </button>
          )}

          {effectiveAgentStateForUi === AgentState.AWAITING_USER_CONFIRMATION && (
            <ConfirmationBanner events={events} />
          )}

          {/* Input Bar */}
          <div className="border-t border-border/40 bg-card/85 p-3 backdrop-blur-sm dark:bg-card/75">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              accept={CHAT_FILE_INPUT_ACCEPT}
              onChange={(e) => {
                addPendingFiles(e.target.files ?? []);
                e.target.value = "";
              }}
            />
            <div className="relative mx-auto flex max-w-[720px] flex-col gap-2">
              {pendingFiles.length > 0 && (
                <div className="flex flex-wrap gap-1.5 px-0.5">
                  {pendingFiles.map((f, i) => (
                    <span
                      key={`${f.name}-${f.size}-${i}`}
                      className="inline-flex max-w-[220px] items-center gap-1 rounded-md bg-muted/55 px-2 py-0.5 text-[11px] text-muted-foreground ring-1 ring-border/35"
                    >
                      <span className="truncate" title={f.name}>
                        {f.name}
                      </span>
                      <button
                        type="button"
                        className="shrink-0 rounded p-0.5 hover:bg-muted/50"
                        aria-label={`Remove ${f.name}`}
                        onClick={() =>
                          setPendingFiles((prev) => prev.filter((_, j) => j !== i))
                        }
                      >
                        <X className="h-3 w-3 opacity-70" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-end gap-2">
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className={cn(
                        "h-9 w-9 shrink-0 rounded-lg",
                        !canOpenFilePicker && "opacity-40",
                      )}
                      aria-label="Attach files"
                      aria-disabled={!canOpenFilePicker}
                      onClick={() => {
                        if (!canOpenFilePicker) {
                          if (needsSetup) {
                            toast.info("Finish setup first", {
                              description:
                                "Set your API key and model in Settings, then you can attach files.",
                            });
                          } else if (!isDraft && !isConnected) {
                            toast.info("Not connected", {
                              description: everConnected
                                ? "Reconnect or refresh, then try again."
                                : "Still connecting to the server…",
                            });
                          }
                          return;
                        }
                        fileInputRef.current?.click();
                      }}
                    >
                      <Paperclip className="h-4 w-4" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top" className="max-w-xs text-xs">
                    Attach files or images (JPEG/PNG/GIF/WebP). Text/code go to the workspace; images
                    are sent to the model when it supports vision (max {CHAT_IMAGE_MAX_COUNT} images,{" "}
                    {Math.round(CHAT_IMAGE_MAX_BYTES / (1024 * 1024))} MB each).
                  </TooltipContent>
                </Tooltip>

                <div className="relative min-w-0 flex-1">
                  {playbookMatch !== null && playbooks.length > 0 && (
                    <PlaybookAutocomplete
                      playbooks={playbooks}
                      filter={playbookMatch}
                      onSelect={(pb) => setInputValue(`/${pb.name} `)}
                    />
                  )}
                  <Textarea
                    placeholder={
                      isDraft
                        ? needsSetup
                          ? "Set API key and model in Settings to start."
                          : "Message the agent… (chat is created when you send)"
                        : !isConnected
                          ? everConnected
                            ? "Disconnected — refresh or wait for reconnect…"
                            : "Connecting…"
                          : needsSetup
                            ? "Set API key and model in Settings to start."
                            : canSend
                              ? "Message the agent… (/ for playbooks, paperclip to attach)"
                              : "Agent is running…"
                    }
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={!canSend || isUploading}
                    className="min-h-10 max-h-37.5 w-full resize-none rounded-xl border-muted-foreground/20 bg-muted/30 text-sm"
                    rows={1}
                  />
                </div>
                <Button
                  size="icon"
                  className="h-9 w-9 shrink-0 rounded-lg"
                  onClick={() => void handleSend()}
                  disabled={
                    !canSend ||
                    isUploading ||
                    (!inputValue.trim() && pendingFiles.length === 0)
                  }
                >
                  {isUploading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </div>
      </div>
    </div>
  );
}
