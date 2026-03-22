import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { getWorkspace, setWorkspacePath } from "@/api/workspace";
import { useSessionStore } from "@/stores/session-store";

export function useWorkspace() {
  return useQuery({
    queryKey: ["workspace"],
    queryFn: getWorkspace,
    staleTime: 15_000,
  });
}

export function useSetWorkspace() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: (path: string) => setWorkspacePath(path),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workspace"] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      useSessionStore.getState().clearSession();
      navigate("/");
      toast.success("Project folder updated. Chats for this folder load in the sidebar.");
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "response" in err
          ? String(
              (err as { response?: { data?: { detail?: string } } }).response?.data
                ?.detail ?? "Could not set workspace",
            )
          : "Could not set workspace";
      toast.error(msg);
    },
  });
}

