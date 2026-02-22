import { useQuery } from "@tanstack/react-query";
import { getPlaybooks } from "@/api/playbooks";

export function usePlaybooks(conversationId: string | undefined) {
  return useQuery({
    queryKey: ["playbooks", conversationId],
    queryFn: () => getPlaybooks(conversationId!),
    enabled: !!conversationId,
    staleTime: 30_000,
  });
}
