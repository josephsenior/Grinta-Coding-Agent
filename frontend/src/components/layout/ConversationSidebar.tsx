import { useState } from "react";
import { useNavigate, useMatch } from "react-router-dom";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "cmdk";
import {
  Plus,
  Trash2,
  Loader2,
  MessageSquare,
  Clock,
  PanelLeftClose,
  Search,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  useConversations,
  useDeleteConversation,
  useDeleteAllConversations,
} from "@/hooks/use-conversations";
import { useNewConversation } from "@/hooks/use-new-conversation";
import { ConversationStatus } from "@/types/conversation";
import type { ConversationInfo } from "@/types/conversation";
import { formatRelativeTime } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app-store";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CMDK_CONTENT, CMDK_OVERLAY, CMDK_ROOT } from "@/components/common/cmdk-palette-classes";

function statusDot(status: ConversationStatus) {
  switch (status) {
    case ConversationStatus.RUNNING:
      return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-green-500 animate-pulse" />;
    case ConversationStatus.STARTING:
      return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />;
    case ConversationStatus.PAUSED:
      return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />;
    default:
      return <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground/40" />;
  }
}

function ConversationRow({
  conversation,
  active,
  onDelete,
}: {
  conversation: ConversationInfo;
  active: boolean;
  onDelete: (id: string) => void;
}) {
  const navigate = useNavigate();

  return (
    <div
      className={cn(
        "group flex w-full cursor-pointer items-start gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors",
        active
          ? "bg-accent text-accent-foreground"
          : "hover:bg-muted/60",
      )}
      onClick={() => navigate(`/chat/${conversation.conversation_id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") navigate(`/chat/${conversation.conversation_id}`);
      }}
    >
      <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {statusDot(conversation.status)}
          <span className="truncate font-medium leading-tight">
            {conversation.title || "Untitled"}
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
          <Clock className="h-2.5 w-2.5 shrink-0" />
          {formatRelativeTime(conversation.last_updated_at)}
        </div>
      </div>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7 shrink-0 opacity-0 group-hover:opacity-100"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(conversation.conversation_id);
        }}
        aria-label="Delete conversation"
      >
        <Trash2 className="h-3 w-3 text-destructive" />
      </Button>
    </div>
  );
}

export function ConversationSidebar() {
  const navigate = useNavigate();
  const match = useMatch("/chat/:id");
  const activeId = match?.params.id ?? null;

  const { data, isLoading, error } = useConversations();
  const deleteMutation = useDeleteConversation();
  const deleteAllMutation = useDeleteAllConversations();
  const { create: handleCreate, isPending: isCreating } = useNewConversation();
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);

  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [isDeletingAll, setIsDeletingAll] = useState(false);
  const [conversationSearchOpen, setConversationSearchOpen] = useState(false);

  const conversations = data?.results ?? [];

  const handleDelete = () => {
    if (!deleteTarget) return;
    const removedId = deleteTarget;
    deleteMutation.mutate(removedId, {
      onSuccess: () => {
        toast.success("Conversation deleted");
        setDeleteTarget(null);
        if (activeId === removedId) {
          navigate("/chat/new");
        }
      },
      onError: () => {
        toast.error("Failed to delete conversation");
      },
    });
  };

  const handleDeleteAll = () => {
    deleteAllMutation.mutate(undefined, {
      onSuccess: () => {
        toast.success("All conversations deleted");
        setIsDeletingAll(false);
        navigate("/chat/new");
      },
      onError: () => {
        toast.error("Failed to delete all conversations");
      },
    });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1 border-b px-2 py-2">
        <span className="flex-1 truncate px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Chats
        </span>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              onClick={() => setConversationSearchOpen(true)}
              aria-label="Search conversations"
            >
              <Search className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Search conversations</TooltipContent>
        </Tooltip>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => handleCreate()}
          disabled={isCreating}
          title="New conversation"
        >
          {isCreating ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
        </Button>
        {conversations.length > 0 && (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0 text-destructive hover:text-destructive"
            title="Delete all conversations"
            onClick={() => setIsDeletingAll(true)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          title="Hide sidebar"
          onClick={() => setSidebarOpen(false)}
        >
          <PanelLeftClose className="h-4 w-4" />
        </Button>
      </div>

      <div className="min-h-0 flex-1">
        {isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : error ? (
          <div className="space-y-2 p-3 text-center text-xs text-muted-foreground">
            <p className="font-medium text-destructive">Couldn&apos;t load conversations</p>
            <p className="text-[11px] leading-relaxed">
              Start the Forge API, confirm the app points at the right URL, then reload the page or wait —
              the list will refresh automatically when the server responds.
            </p>
          </div>
        ) : conversations.length === 0 ? (
          <div className="space-y-1 p-3 text-center text-xs text-muted-foreground">
            <p>No conversations yet.</p>
            <p className="text-[11px] leading-relaxed text-muted-foreground/90">
              Press <span className="font-medium text-foreground/80">+</span> to start a new chat with the agent.
            </p>
          </div>
        ) : (
          <ScrollArea className="h-full">
            <div className="flex flex-col gap-0.5 p-1">
              {conversations.map((conv) => (
                <ConversationRow
                  key={conv.conversation_id}
                  conversation={conv}
                  active={conv.conversation_id === activeId}
                  onDelete={setDeleteTarget}
                />
              ))}
            </div>
          </ScrollArea>
        )}
      </div>

      <Dialog open={isDeletingAll} onOpenChange={(open) => !open && setIsDeletingAll(false)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete all conversations?</DialogTitle>
            <DialogDescription>
              This will permanently delete all conversations and their history. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDeletingAll(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteAll}
              disabled={deleteAllMutation.isPending}
            >
              {deleteAllMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Delete all
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete conversation?</DialogTitle>
            <DialogDescription>
              This cannot be undone. The conversation and its data will be removed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CommandDialog
        open={conversationSearchOpen}
        onOpenChange={setConversationSearchOpen}
        label="Search conversations"
        overlayClassName={CMDK_OVERLAY}
        contentClassName={CMDK_CONTENT}
        className={CMDK_ROOT}
      >
        <CommandInput placeholder="Search conversations…" />
        <CommandList className="max-h-[min(55vh,400px)] min-h-0 overflow-x-hidden overflow-y-auto">
          <CommandEmpty>
            {isLoading
              ? "Loading…"
              : error
                ? "Couldn’t load conversations."
                : conversations.length === 0
                  ? "No conversations yet."
                  : "No matching conversations."}
          </CommandEmpty>

          {!isLoading && !error && conversations.length > 0 && (
            <CommandGroup heading="Conversations">
              {conversations.map((conv) => {
                const title = conv.title || "Untitled";
                return (
                  <CommandItem
                    key={conv.conversation_id}
                    value={`${title} ${conv.conversation_id}`}
                    onSelect={() => {
                      setConversationSearchOpen(false);
                      navigate(`/chat/${conv.conversation_id}`);
                    }}
                  >
                    <MessageSquare className="h-4 w-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{title}</span>
                  </CommandItem>
                );
              })}
            </CommandGroup>
          )}
        </CommandList>
      </CommandDialog>
    </div>
  );
}
