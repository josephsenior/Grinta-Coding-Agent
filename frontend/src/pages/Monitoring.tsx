import { useQuery } from "@tanstack/react-query";
import { Activity, RefreshCw, CheckCircle, XCircle, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface HealthReady {
  status: string;
  uptime_seconds: number;
  checks: {
    config: { status: string; workspace_base?: string; detail?: string };
    storage: { status: string; path?: string; detail?: string };
  };
}

function formatUptime(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${m}m`;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "ok")
    return <CheckCircle className="h-4 w-4 text-green-500" />;
  if (status === "degraded")
    return <AlertCircle className="h-4 w-4 text-yellow-500" />;
  return <XCircle className="h-4 w-4 text-red-500" />;
}

function CheckRow({
  label,
  check,
}: {
  label: string;
  check: { status: string; [key: string]: string | undefined };
}) {
  const detail = check.workspace_base ?? check.path ?? check.detail;
  return (
    <div className="flex items-start gap-3 rounded-lg border px-4 py-3">
      <StatusIcon status={check.status} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{label}</span>
          <Badge
            variant={check.status === "ok" ? "outline" : "destructive"}
            className="text-[10px] h-4 px-1"
          >
            {check.status}
          </Badge>
        </div>
        {detail && (
          <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
            {detail}
          </p>
        )}
      </div>
    </div>
  );
}

export default function Monitoring() {
  const { data, isLoading, isError, dataUpdatedAt, refetch, isFetching } =
    useQuery<HealthReady>({
      queryKey: ["health-ready"],
      queryFn: async () => {
        const res = await fetch("/api/health/ready");
        return res.json();
      },
      refetchInterval: 30_000,
      retry: 0,
    });

  const lastChecked = dataUpdatedAt
    ? new Date(dataUpdatedAt).toLocaleTimeString()
    : null;

  const overallOk = !isError && data?.status === "ok";

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col px-6 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Activity className="h-6 w-6" />
          <h1 className="text-2xl font-bold">Monitoring</h1>
        </div>
        <div className="flex items-center gap-2">
          {lastChecked && (
            <span className="text-xs text-muted-foreground">
              Checked {lastChecked}
            </span>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw
              className={cn("h-4 w-4", isFetching && "animate-spin")}
            />
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
          Interrogating backend telemetry&hellip;
        </div>
      ) : isError || !data ? (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4">
          <div className="flex items-center gap-2 text-destructive text-sm font-medium">
            <XCircle className="h-4 w-4" />
            Backend unreachable
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Verify API engine is active on port 3000.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Overall status */}
          <div
            className={cn(
              "flex items-center justify-between rounded-lg border p-4",
              overallOk
                ? "border-green-500/30 bg-green-500/5"
                : "border-yellow-500/30 bg-yellow-500/5",
            )}
          >
            <div className="flex items-center gap-3">
              <span
                className={cn(
                  "h-3 w-3 rounded-full",
                  overallOk ? "bg-green-500" : "bg-yellow-400",
                )}
              />
              <div>
                <p className="text-sm font-semibold">
                  {overallOk ? "All systems operational" : "Degraded"}
                </p>
                <p className="text-xs text-muted-foreground">
                  Uptime: {formatUptime(data.uptime_seconds)}
                </p>
              </div>
            </div>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                overallOk
                  ? "border-green-500/50 text-green-600"
                  : "border-yellow-500/50 text-yellow-600",
              )}
            >
              {data.status}
            </Badge>
          </div>

          {/* Subsystem checks */}
          <div>
            <h2 className="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              Subsystems
            </h2>
            <div className="space-y-2">
              <CheckRow label="Configuration" check={data.checks.config} />
              <CheckRow label="File Storage" check={data.checks.storage} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

