import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { getWorkspace, setWorkspacePath } from "@/api/workspace";
import { useSessionStore } from "@/stores/session-store";

function formatWorkspaceSetError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const d = err.response?.data as { detail?: unknown } | undefined;
    const detail = d?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail)) {
      const parts = detail.map((x) =>
        typeof x === "object" && x !== null && "msg" in x
          ? String((x as { msg: string }).msg)
          : JSON.stringify(x),
      );
      if (parts.length) {
        return parts.join("; ");
      }
    }
    if (err.code === "ECONNABORTED") {
      return "Request timed out while switching workspace — try again or close active chats first.";
    }
  }
  return "Could not set workspace";
}

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
      toast.error(formatWorkspaceSetError(err));
    },
  });
}

