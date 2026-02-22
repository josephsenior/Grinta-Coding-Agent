import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Trash2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  useConversations,
  useDeleteConversation,
} from "@/hooks/use-conversations";
import { ConversationStatus } from "@/types/conversation";
import type { ConversationInfo } from "@/types/conversation";
import { formatRelativeTime } from "@/lib/utils";
import { NewConversationDialog } from "@/components/common/NewConversationDialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";

function statusBadge(status: ConversationStatus) {
  switch (status) {
    case ConversationStatus.RUNNING:
      return <Badge variant="success" className="gap-1"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />Running</Badge>;
    case ConversationStatus.STARTING:
      return <Badge variant="warning">Starting</Badge>;
    case ConversationStatus.STOPPED:
      return <Badge variant="secondary">Stopped</Badge>;
    case ConversationStatus.PAUSED:
      return <Badge variant="warning">Paused</Badge>;
    case ConversationStatus.ARCHIVED:
      return <Badge variant="outline">Archived</Badge>;
    default:
      return <Badge variant="secondary">Unknown</Badge>;
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
      className="group flex cursor-pointer items-center justify-between rounded-lg border bg-card p-4 transition-colors hover:bg-accent"
      onClick={() => navigate(`/chat/${conversation.conversation_id}`)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter") navigate(`/chat/${conversation.conversation_id}`);
      }}
    >
      <div className="flex flex-col gap-1.5 min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="truncate font-medium text-sm">
            {conversation.title || "Untitled conversation"}
          </h3>
          {statusBadge(conversation.status)}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          {conversation.selected_repository && (
            <span className="truncate max-w-[200px]">
              {conversation.selected_repository}
              {conversation.selected_branch && `:${conversation.selected_branch}`}
            </span>
          )}
          <span>{formatRelativeTime(conversation.last_updated_at)}</span>
        </div>
      </div>

      <Button
        variant="ghost"
        size="icon"
        className="opacity-0 group-hover:opacity-100 shrink-0"
        onClick={(e) => {
          e.stopPropagation();
          onDelete(conversation.conversation_id);
        }}
      >
        <Trash2 className="h-4 w-4 text-destructive" />
      </Button>
    </div>
  );
}

export default function Home() {
  const { data, isLoading, error } = useConversations();
  const deleteMutation = useDeleteConversation();
  const [newDialogOpen, setNewDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

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

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col px-6 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Conversations</h1>
          <p className="text-sm text-muted-foreground">
            Manage your AI coding sessions
          </p>
        </div>
        <Button onClick={() => setNewDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New Conversation
        </Button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : error ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
          <p>Failed to load conversations</p>
          <p className="text-xs">Is the backend running on port 3000?</p>
        </div>
      ) : conversations.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
          <div className="rounded-full bg-muted p-6">
            <Plus className="h-10 w-10 text-muted-foreground" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">No conversations yet</h2>
            <p className="text-sm text-muted-foreground">
              Start your first AI coding session
            </p>
          </div>
          <Button onClick={() => setNewDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            New Conversation
          </Button>
        </div>
      ) : (
        <ScrollArea className="flex-1">
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

      {/* New Conversation Dialog */}
      <NewConversationDialog
        open={newDialogOpen}
        onOpenChange={setNewDialogOpen}
      />

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
