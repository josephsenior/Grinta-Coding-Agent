import { useQuery } from "@tanstack/react-query";

interface HealthLive {
  status: string;
  uptime_seconds: number;
}

async function fetchHealth(): Promise<HealthLive> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), 3000);
  try {
    const res = await fetch("/api/health/live", { signal: controller.signal });
    if (!res.ok) throw new Error("unhealthy");
    return res.json();
  } finally {
    clearTimeout(id);
  }
}

export function useBackendHealth() {
  const { data, isError, isLoading } = useQuery({
    queryKey: ["backend-health"],
    queryFn: fetchHealth,
    refetchInterval: 10_000,
    retry: 0,
    staleTime: 8_000,
  });

  if (isLoading) return { connected: null, uptime_seconds: undefined };
  return {
    connected: !isError && data?.status === "ok",
    uptime_seconds: data?.uptime_seconds,
  };
}
