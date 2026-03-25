import { useQuery } from "@tanstack/react-query";
import { getPlaybooks } from "@/api/playbooks";

export function usePlaybooks(conversationId: string | undefined) {
  const ready = !!conversationId && conversationId !== "new";
  return useQuery({
    queryKey: ["playbooks", conversationId],
    queryFn: () => getPlaybooks(conversationId!),
    enabled: ready,
    staleTime: 30_000,
  });
}
