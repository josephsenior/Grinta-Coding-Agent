import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateConversation } from "@/hooks/use-conversations";
import { toast } from "sonner";

interface NewConversationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function NewConversationDialog({
  open,
  onOpenChange,
}: NewConversationDialogProps) {
  const navigate = useNavigate();
  const createMutation = useCreateConversation();
  const [message, setMessage] = useState("");
  const [repository, setRepository] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    createMutation.mutate(
      {
        initial_message: message || undefined,
        selected_repository: repository || undefined,
      },
      {
        onSuccess: (conv) => {
          onOpenChange(false);
          setMessage("");
          setRepository("");
          navigate(`/chat/${conv.conversation_id}`);
        },
        onError: () => {
          toast.error("Failed to create conversation");
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>New Conversation</DialogTitle>
            <DialogDescription>
              Start a new AI coding session. Describe what you'd like to build.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4">
            <Textarea
              placeholder="What would you like to build?"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              className="min-h-[100px]"
              autoFocus
            />
            <Input
              placeholder="Repository path (optional)"
              value={repository}
              onChange={(e) => setRepository(e.target.value)}
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : null}
              Start
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
