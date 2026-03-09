import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Trash2,
  Loader2,
  MessageSquare,
  GitBranch,
  Clock,
  Hammer,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
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

function statusBadge(status: ConversationStatus) {
  switch (status) {
    case ConversationStatus.RUNNING:
      return <Badge variant="success" className="gap-1 text-[10px] h-5"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />Running</Badge>;
    case ConversationStatus.STARTING:
      return <Badge variant="warning" className="text-[10px] h-5">Starting</Badge>;
    case ConversationStatus.STOPPED:
      return <Badge variant="secondary" className="text-[10px] h-5">Stopped</Badge>;
    case ConversationStatus.PAUSED:
      return <Badge variant="warning" className="text-[10px] h-5">Paused</Badge>;
    case ConversationStatus.ARCHIVED:
      return <Badge variant="outline" className="text-[10px] h-5">Archived</Badge>;
    default:
      return <Badge variant="secondary" className="text-[10px] h-5">Unknown</Badge>;
  }
}

function ConversationCard({
  conversation,
  onDelete,
}: {
  conversation: ConversationInfo;
  onDelete: (id: string) => void;
}) {
  const navigate = useNavigate();

  return (
    <div
      className={cn(
        "group relative flex cursor-pointer items-center gap-4 rounded-xl border p-4 transition-all",
        "hover:bg-accent/50 hover:border-accent-foreground/10 hover:shadow-sm",
        conversation.status === ConversationStatus.RUNNING && "border-green-500/20 bg-green-500/[0.02]",
      )}
      onClick={() => navigate(`/chat/${conversation.conversation_id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") navigate(`/chat/${conversation.conversation_id}`);
      }}
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted">
        <MessageSquare className="h-4 w-4 text-muted-foreground" />
      </div>

      <div className="flex flex-col gap-1 min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="truncate font-medium text-sm">
            {conversation.title || "Untitled conversation"}
          </h3>
          {statusBadge(conversation.status)}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {conversation.selected_repository && (
            <span className="flex items-center gap-1 truncate max-w-[200px]">
              <GitBranch className="h-3 w-3 shrink-0" />
              {conversation.selected_repository}
              {conversation.selected_branch && `:${conversation.selected_branch}`}
            </span>
          )}
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3 shrink-0" />
            {formatRelativeTime(conversation.last_updated_at)}
          </span>
        </div>
      </div>

      <Button
        variant="ghost"
        size="icon"
        className="h-8 w-8 opacity-0 group-hover:opacity-100 shrink-0 transition-opacity"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(conversation.conversation_id);
        }}
      >
        <Trash2 className="h-3.5 w-3.5 text-destructive" />
      </Button>
    </div>
  );
}

export default function Home() {
  const { data, isLoading, error } = useConversations();
  const deleteMutation = useDeleteConversation();
  const deleteAllMutation = useDeleteAllConversations();
  const { create: handleCreate, isPending: isCreating } = useNewConversation();
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [isDeletingAll, setIsDeletingAll] = useState(false);

  const conversations = data?.results ?? [];

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate(deleteTarget, {
      onSuccess: () => {
        toast.success("Conversation deleted");
        setDeleteTarget(null);
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
      },
      onError: () => {
        toast.error("Failed to delete all conversations");
      },
    });
  };

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col px-6 py-8">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">Conversations</h1>
          <p className="text-sm text-muted-foreground">
            {conversations.length > 0
              ? `${conversations.length} session${conversations.length !== 1 ? "s" : ""}`
                : "Initialize AI sequence"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {conversations.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              className="h-9 gap-2 text-destructive hover:text-destructive hover:bg-destructive/10 border-destructive/20"
              onClick={() => setIsDeletingAll(true)}
              disabled={deleteAllMutation.isPending}
            >
              <Trash2 className="h-4 w-4" />
              Delete All
            </Button>
          )}
          <Button onClick={handleCreate} disabled={isCreating} className="gap-2 h-9">
            {isCreating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            New Conversation
          </Button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : error ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
            <span className="text-destructive text-lg">!</span>
          </div>
          <div className="space-y-1">
            <p className="text-sm font-medium">Cannot reach backend</p>
            <p className="text-xs text-muted-foreground">
              Make sure the Forge backend is running on port 3000
            </p>
          </div>
        </div>
      ) : conversations.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
            <Hammer className="h-8 w-8 text-primary" />
          </div>
          <div className="space-y-2">
            <h2 className="text-lg font-semibold">Datastore Empty</h2>
            <p className="max-w-sm text-sm text-muted-foreground leading-relaxed">
              Initialize a new active workspace to commence engineering procedures.
            </p>
          </div>
          <Button onClick={handleCreate} disabled={isCreating} size="lg" className="gap-2">
            {isCreating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Plus className="h-4 w-4" />
            )}
            New Conversation
          </Button>
        </div>
      ) : (
        <ScrollArea className="flex-1 -mx-1 px-1">
          <div className="flex flex-col gap-2">
            {conversations.map((conv) => (
              <ConversationCard
                key={conv.conversation_id}
                conversation={conv}
                onDelete={setDeleteTarget}
              />
            ))}
          </div>
        </ScrollArea>
      )}

      {/* Delete All Confirmation Dialog */}
      <Dialog
        open={isDeletingAll}
        onOpenChange={(open) => !open && setIsDeletingAll(false)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete all conversations?</DialogTitle>
            <DialogDescription>
              This will permanently delete all conversations and their history.
              This action cannot be undone.
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
              Delete All
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete conversation?</DialogTitle>
            <DialogDescription>
              This action cannot be undone. The conversation and all its data
              will be permanently removed.
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
    </div>
  );
}
