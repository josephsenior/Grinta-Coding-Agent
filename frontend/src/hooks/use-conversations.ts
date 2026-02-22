import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getConversations,
  getConversation,
  createConversation,
  deleteConversation,
  updateConversationTitle,
} from "@/api/conversations";
import type { CreateConversationRequest } from "@/types/conversation";

export function useConversations(pageId?: string) {
  return useQuery({
    queryKey: ["conversations", pageId],
    queryFn: () => getConversations(pageId),
    refetchInterval: 5000,
  });
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => getConversation(id!),
    enabled: !!id,
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (req: CreateConversationRequest) => createConversation(req),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteConversation(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useUpdateConversationTitle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      updateConversationTitle(id, title),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}
