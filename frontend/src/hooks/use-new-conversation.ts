import { useNavigate } from "react-router-dom";
import { useCreateConversation } from "./use-conversations";
import { toast } from "sonner";

export function useNewConversation() {
  const navigate = useNavigate();
  const createMutation = useCreateConversation();

  const create = () => {
    createMutation.mutate(
      {},
      {
        onSuccess: (conv) => {
          navigate(`/chat/${conv.conversation_id}`);
        },
        onError: () => {
          toast.error("Failed to create conversation");
        },
      },
    );
  };

  return {
    create,
    isPending: createMutation.isPending,
  };
}
