import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Settings as SettingsIcon,
  Bot,
  Server,
  Eye,
  EyeOff,
  Plus,
  Trash2,
  Pencil,
  Check,
  Loader2,
  ChevronRight,
  Activity,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { getSettings, saveSettings } from "@/api/settings";
import type {
  MCPServerConfig,
  RecoverySnapshot,
  SettingsResponse,
  StartupSnapshot,
} from "@/types/settings";
import { cn } from "@/lib/utils";
import Monitoring from "./Monitoring";

function renderBoolBadge(value: boolean | undefined, trueLabel = "Yes", falseLabel = "No") {
  if (value === undefined) {
    return (
      <Badge variant="secondary" className="h-5 text-[10px]">
        Unknown
      </Badge>
    );
  }
  return value ? (
    <Badge className="h-5 border-green-500/50 bg-green-500/10 text-green-600 text-[10px]" variant="outline">
      {trueLabel}
    </Badge>
  ) : (
    <Badge variant="secondary" className="h-5 text-[10px]">
      {falseLabel}
    </Badge>
  );
}

function formatRecordedAt(timestamp: number | undefined): string | null {
  if (!timestamp || !Number.isFinite(timestamp)) return null;
  const millis = timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000;
  return new Date(millis).toLocaleString();
}

function StartupDetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border px-3 py-2">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <div className={cn("text-right text-xs", mono && "font-mono")}>{value}</div>
    </div>
  );
}

function StartupSection({ settings }: { settings: SettingsResponse }) {
  const snapshot = settings.startup_snapshot as StartupSnapshot | null | undefined;
  const recovery = settings.recovery_snapshot as RecoverySnapshot | null | undefined;
  const recordedAt = formatRecordedAt(snapshot?.recorded_at);
  const latestRestore = recovery?.state_restores?.recent?.[0];
  const latestRestoreAt = formatRecordedAt(
    typeof latestRestore?.recorded_at === "number" ? latestRestore.recorded_at : undefined,
  );

  const recoveryBadge = (() => {
    switch (recovery?.status) {
      case "ok":
        return (
          <Badge className="h-5 border-green-500/50 bg-green-500/10 text-green-600 text-[10px]" variant="outline">
            Recovery healthy
          </Badge>
        );
      case "degraded":
        return (
          <Badge className="h-5 border-amber-500/50 bg-amber-500/10 text-amber-700 text-[10px]" variant="outline">
            Recovery degraded
          </Badge>
        );
      case "error":
        return (
          <Badge className="h-5 border-destructive/50 bg-destructive/10 text-destructive text-[10px]" variant="outline">
            Recovery error
          </Badge>
        );
      default:
        return (
          <Badge variant="secondary" className="h-5 text-[10px]">
            Recovery unknown
          </Badge>
        );
    }
  })();

  return (
    <section>
      <div className="mb-4 flex items-center gap-2">
        <Activity className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-semibold">Startup Status</h2>
      </div>

      {!snapshot ? (
        <div className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
          Startup snapshot is not available yet. Start the backend through the canonical server path and reload settings.
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg border px-4 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Local server snapshot</span>
              {snapshot.runtime ? (
                <Badge variant="outline" className="h-5 px-1.5 font-mono text-[10px]">
                  {snapshot.runtime}
                </Badge>
              ) : null}
              {renderBoolBadge(snapshot.reload_enabled, "Reload on", "Reload off")}
              {snapshot.port_auto_switched ? (
                <Badge variant="secondary" className="h-5 text-[10px]">
                  Port auto-switched
                </Badge>
              ) : null}
              {recoveryBadge}
            </div>
            {recordedAt ? (
              <p className="mt-2 text-xs text-muted-foreground">Captured {recordedAt}</p>
            ) : (
              <p className="mt-2 text-xs text-muted-foreground">
                Shows the resolved startup plan currently recorded by the backend.
              </p>
            )}
          </div>

          <div className="rounded-lg border px-4 py-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium">Recovery provenance</span>
              {latestRestore?.source ? (
                <Badge variant="outline" className="h-5 px-1.5 font-mono text-[10px]">
                  {latestRestore.source}
                </Badge>
              ) : null}
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              {latestRestore
                ? `Latest restore ${latestRestoreAt ? `captured ${latestRestoreAt}` : "recorded recently"}.`
                : "No recent restore fallback has been recorded."}
            </p>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              <StartupDetailRow
                label="Latest Restore Source"
                value={latestRestore?.source ?? "None recorded"}
                mono
              />
              <StartupDetailRow
                label="Restore Count"
                value={recovery?.state_restores?.count ?? 0}
                mono
              />
              <StartupDetailRow
                label="Restore Path"
                value={latestRestore?.path ?? "Not applicable"}
                mono
              />
              <StartupDetailRow
                label="Primary Restore Error"
                value={latestRestore?.primary_error ?? "None"}
              />
              <StartupDetailRow
                label="Persist Failures"
                value={recovery?.event_streams?.persist_failures ?? 0}
                mono
              />
              <StartupDetailRow
                label="Durable Writer Errors"
                value={recovery?.event_streams?.durable_writer_errors ?? 0}
                mono
              />
            </div>
          </div>

          <div className="grid gap-2 md:grid-cols-2">
            <StartupDetailRow
              label="Host / Port"
              value={
                snapshot.resolved_port !== undefined
                  ? `${snapshot.host ?? "127.0.0.1"}:${snapshot.resolved_port}`
                  : (snapshot.host ?? "Unknown")
              }
              mono
            />
            <StartupDetailRow
              label="Requested Port"
              value={snapshot.requested_port ?? "Unknown"}
              mono
            />
            <StartupDetailRow
              label=".env.local"
              value={renderBoolBadge(snapshot.dotenv_local_loaded, "Loaded", "Not loaded")}
            />
            <StartupDetailRow
              label="agent.yaml in cwd"
              value={renderBoolBadge(snapshot.agent_config_present, "Present", "Missing")}
            />
            <StartupDetailRow
              label="Project Root"
              value={snapshot.project_root ?? "Unknown"}
              mono
            />
            <StartupDetailRow
              label="Settings Path"
              value={snapshot.settings_path ?? "Unknown"}
              mono
            />
            <StartupDetailRow label="UI URL" value={snapshot.ui_url ?? "Unknown"} mono />
            <StartupDetailRow label="Health URL" value={snapshot.health_url ?? "Unknown"} mono />
          </div>

          <details className="rounded-lg border px-4 py-3">
            <summary className="cursor-pointer text-sm font-medium">More startup details</summary>
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              <StartupDetailRow label="API URL" value={snapshot.api_url ?? "Unknown"} mono />
              <StartupDetailRow label="Docs URL" value={snapshot.docs_url ?? "Unknown"} mono />
              <StartupDetailRow label="Current Working Dir" value={snapshot.cwd ?? "Unknown"} mono />
              <StartupDetailRow label="App Root" value={snapshot.app_root ?? "Unknown"} mono />
            </div>
          </details>
        </div>
      )}
    </section>
  );
}

// ─── Model Section ────────────────────────────────────────────────────────────

function ModelSection({
  settings,
  onSave,
}: {
  settings: SettingsResponse;
  onSave: (patch: Partial<SettingsResponse>) => Promise<void>;
}) {
  const [model, setModel] = useState(settings.llm_model ?? "");
  const [provider, setProvider] = useState(settings.llm_provider ?? "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(settings.llm_base_url ?? "");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);

  const isDirty =
    model !== (settings.llm_model ?? "") ||
    provider !== (settings.llm_provider ?? "") ||
    apiKey !== "" ||
    baseUrl !== (settings.llm_base_url ?? "");

  const [errors, setErrors] = useState<{ model?: string; provider?: string; baseUrl?: string }>({});

  const validate = (): boolean => {
    const next: typeof errors = {};
    if (!model.trim()) next.model = "Model is required";
    if (!provider.trim()) next.provider = "Provider is required";
    if (baseUrl.trim() && !/^https?:\/\/.+/.test(baseUrl.trim()))
      next.baseUrl = "Must be a valid URL starting with http:// or https://";
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try {
      const body: Record<string, unknown> = {
        llm_model: model.trim(),
        llm_provider: provider.trim().toLowerCase(),
        llm_base_url: baseUrl.trim() || null,
      };
      if (apiKey) body.llm_api_key = apiKey;
      await onSave(body as Partial<SettingsResponse>);
      setApiKey("");
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <div className="mb-4 flex items-center gap-2">
        <Bot className="h-4 w-4 text-muted-foreground" />
        <h2 className="text-base font-semibold">Model</h2>
      </div>

      <div className="space-y-4">
        {/* Model name */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">Provider</label>
          <Input
            placeholder="e.g. openai, anthropic, google, groq, openhands, ollama"
            value={provider}
            onChange={(e) => { setProvider(e.target.value); setErrors((p) => ({ ...p, provider: undefined })); }}
            className={cn("font-mono text-sm", errors.provider && "border-destructive")}
          />
          {errors.provider && <p className="text-xs text-destructive">{errors.provider}</p>}
          <p className="text-xs text-muted-foreground">
            Explicit provider id used for routing and API key selection.
          </p>
        </div>

        <div className="space-y-1.5">
          <label className="text-sm font-medium">Model</label>
          <Input
            placeholder="e.g. claude-sonnet-4-20250514"
            value={model}
            onChange={(e) => { setModel(e.target.value); setErrors((p) => ({ ...p, model: undefined })); }}
            className={cn("font-mono text-sm", errors.model && "border-destructive")}
          />
          {errors.model && <p className="text-xs text-destructive">{errors.model}</p>}
          <p className="text-xs text-muted-foreground">
            Raw model id for the selected provider — e.g.{" "}
            <code className="rounded bg-muted px-1">claude-3-5-sonnet</code>,{" "}
            <code className="rounded bg-muted px-1">gpt-4o</code>,{" "}
            <code className="rounded bg-muted px-1">meta-llama/llama-4-scout-17b-16e-instruct</code>
          </p>
        </div>

        {/* API Key */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium">API Key</label>
            {settings.llm_api_key_set ? (
              <Badge variant="outline" className="h-5 border-green-500/50 bg-green-500/10 text-green-600 text-[10px]">
                Set
              </Badge>
            ) : (
              <Badge variant="secondary" className="h-5 text-[10px]">
                Not set
              </Badge>
            )}
          </div>
          <div className="relative">
            <Input
              type={showKey ? "text" : "password"}
              placeholder={
                settings.llm_api_key_set
                  ? "Leave blank to keep existing key"
                  : "sk-..."
              }
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="pr-10 font-mono text-sm"
              autoComplete="off"
              spellCheck={false}
            />
            <button
              type="button"
              tabIndex={-1}
              onClick={() => setShowKey((v) => !v)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            >
              {showKey ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </button>
          </div>
        </div>

        {/* Base URL */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">
            Base URL{" "}
            <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <Input
            placeholder="https://api.openai.com/v1"
            value={baseUrl}
            onChange={(e) => { setBaseUrl(e.target.value); setErrors((p) => ({ ...p, baseUrl: undefined })); }}
            className={cn("font-mono text-sm", errors.baseUrl && "border-destructive")}
          />
          {errors.baseUrl && <p className="text-xs text-destructive">{errors.baseUrl}</p>}
          <p className="text-xs text-muted-foreground">
            Custom endpoint for self-hosted or proxy deployments
          </p>
        </div>

        <Button onClick={handleSave} disabled={!isDirty || saving} size="sm">
          {saving ? (
            <>
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              Saving...
            </>
          ) : (
            <>
              <Check className="mr-2 h-3.5 w-3.5" />
              Save
            </>
          )}
        </Button>
      </div>
    </section>
  );
}

// ─── MCP Server Dialog ────────────────────────────────────────────────────────

const EMPTY_SERVER: MCPServerConfig = {
  name: "",
  type: "stdio",
  command: "",
  args: [],
  env: {},
  url: "",
  api_key: "",
  usage_hint: "",
};

function MCPServerDialog({
  open,
  initial,
  onClose,
  onSave,
}: {
  open: boolean;
  initial: MCPServerConfig | null;
  onClose: () => void;
  onSave: (server: MCPServerConfig) => void;
}) {
  const editing = initial !== null;
  const [form, setForm] = useState<MCPServerConfig>(
    initial ?? { ...EMPTY_SERVER },
  );
  const [argsRaw, setArgsRaw] = useState(
    (initial?.args ?? []).join(" "),
  );
  const [envRaw, setEnvRaw] = useState(
    Object.entries(initial?.env ?? {})
      .map(([k, v]) => `${k}=${v}`)
      .join(", "),
  );

  useEffect(() => {
    if (!open) return;
    const base = initial ?? { ...EMPTY_SERVER };
    setForm(base);
    setArgsRaw((base.args ?? []).join(" "));
    setEnvRaw(
      Object.entries(base.env ?? {})
        .map(([k, v]) => `${k}=${v}`)
        .join(", "),
    );
  }, [open, initial]);

  const set = (key: keyof MCPServerConfig, value: unknown) =>
    setForm((f) => ({ ...f, [key]: value }));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const args = argsRaw.trim() ? argsRaw.trim().split(/\s+/) : [];
    const env: Record<string, string> = {};
    for (const pair of envRaw.split(",")) {
      const trimmed = pair.trim();
      if (!trimmed) continue;
      const idx = trimmed.indexOf("=");
      if (idx > 0)
        env[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
    }
    const usage_hint = (form.usage_hint ?? "").trim() || null;
    onSave({ ...form, args, env, usage_hint });
  };

  const isStdio = form.type === "stdio";
  const isValid =
    form.name.trim() &&
    (isStdio ? !!form.command?.trim() : !!form.url?.trim());

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? "Edit MCP Server" : "Add MCP Server"}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 py-2">
          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Name</label>
            <Input
              placeholder="my-server"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              disabled={editing}
              className="font-mono text-sm"
            />
          </div>

          {/* Type */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Type</label>
            <div className="flex gap-2">
              {(["stdio", "sse", "shttp"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => set("type", t)}
                  className={cn(
                    "rounded-md border px-3 py-1.5 text-xs font-mono transition-colors",
                    form.type === t
                      ? "border-primary bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-accent",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {isStdio ? (
            <>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">Command</label>
                <Input
                  placeholder="npx"
                  value={form.command ?? ""}
                  onChange={(e) => set("command", e.target.value)}
                  className="font-mono text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  Args{" "}
                  <span className="font-normal text-muted-foreground">
                    (space-separated)
                  </span>
                </label>
                <Input
                  placeholder="-y @modelcontextprotocol/server-filesystem /path"
                  value={argsRaw}
                  onChange={(e) => setArgsRaw(e.target.value)}
                  className="font-mono text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  Env{" "}
                  <span className="font-normal text-muted-foreground">
                    (KEY=VALUE, comma-separated)
                  </span>
                </label>
                <Input
                  placeholder="API_KEY=abc123, DEBUG=1"
                  value={envRaw}
                  onChange={(e) => setEnvRaw(e.target.value)}
                  className="font-mono text-sm"
                />
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">URL</label>
                <Input
                  placeholder="https://mcp.example.com/sse"
                  value={form.url ?? ""}
                  onChange={(e) => set("url", e.target.value)}
                  className="font-mono text-sm"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium">
                  API Key{" "}
                  <span className="font-normal text-muted-foreground">
                    (optional)
                  </span>
                </label>
                <Input
                  type="password"
                  placeholder="sk-..."
                  value={form.api_key ?? ""}
                  onChange={(e) => set("api_key", e.target.value)}
                  className="font-mono text-sm"
                />
              </div>
            </>
          )}

          <div className="space-y-1.5">
            <label className="text-sm font-medium">
              Agent usage hint{" "}
              <span className="font-normal text-muted-foreground">
                (optional, system prompt)
              </span>
            </label>
            <Textarea
              placeholder="e.g. Use for up-to-date library docs and API signatures — not guesses from memory."
              value={form.usage_hint ?? ""}
              onChange={(e) => set("usage_hint", e.target.value)}
              className="min-h-18 resize-y font-mono text-sm"
            />
            <p className="text-[11px] text-muted-foreground">
              One short sentence per server: when the agent should prefer this MCP server over others.
            </p>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={!isValid}>
              {editing ? "Save changes" : "Add server"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ─── MCP Section ─────────────────────────────────────────────────────────────

function MCPSection({
  settings,
  onSave,
}: {
  settings: SettingsResponse;
  onSave: (patch: Partial<SettingsResponse>) => Promise<void>;
}) {
  const servers: MCPServerConfig[] = settings.mcp_config?.servers ?? [];
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<MCPServerConfig | null>(null);
  const [saving, setSaving] = useState(false);

  const openAdd = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = (s: MCPServerConfig) => {
    setEditing(s);
    setDialogOpen(true);
  };

  const saveServer = async (server: MCPServerConfig) => {
    setSaving(true);
    try {
      let next: MCPServerConfig[];
      if (editing) {
        next = servers.map((s) => (s.name === editing.name ? server : s));
      } else {
        if (servers.some((s) => s.name === server.name)) {
          toast.error(`A server named "${server.name}" already exists`);
          return;
        }
        next = [...servers, server];
      }
      await onSave({ mcp_config: { servers: next } });
      setDialogOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const deleteServer = async (name: string) => {
    setSaving(true);
    try {
      await onSave({
        mcp_config: { servers: servers.filter((s) => s.name !== name) },
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <section>
      <div className="mb-4 flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Server className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-base font-semibold">MCP Servers</h2>
            {servers.length > 0 && (
              <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">
                {servers.length}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            External tools &amp; integrations for the agent
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={openAdd}
          disabled={saving}
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          Add server
        </Button>
      </div>

      {servers.length === 0 ? (
        <button
          type="button"
          onClick={openAdd}
          className="flex w-full flex-col items-center gap-2 rounded-lg border border-dashed py-8 text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
        >
          <Server className="h-8 w-8 opacity-30" />
          <span className="text-sm">Zero MCP protocols multiplexed</span>
          <span className="text-xs opacity-70">Click to add one</span>
        </button>
      ) : (
        <div className="space-y-2">
          {servers.map((server) => (
            <div
              key={server.name}
              className="flex items-center gap-3 rounded-lg border px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{server.name}</span>
                  <Badge
                    variant="outline"
                    className="h-4 px-1 font-mono text-[10px]"
                  >
                    {server.type}
                  </Badge>
                </div>
                <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                  {server.type === "stdio"
                    ? [server.command, ...(server.args ?? [])]
                        .filter(Boolean)
                        .join(" ")
                    : (server.url ?? "")}
                </p>
                {server.usage_hint ? (
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                    {server.usage_hint}
                  </p>
                ) : null}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => openEdit(server)}
                >
                  <Pencil className="h-3.5 w-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-destructive hover:text-destructive"
                  onClick={() => deleteServer(server.name)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <MCPServerDialog
        open={dialogOpen}
        initial={editing}
        onClose={() => setDialogOpen(false)}
        onSave={saveServer}
      />
    </section>
  );
}

// ─── Sidebar nav item ─────────────────────────────────────────────────────────

type Section = "startup" | "model" | "mcp" | "monitoring";

function SidebarItem({
  label,
  icon: Icon,
  active,
  onClick,
}: {
  label: string;
  icon: React.ElementType;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm transition-colors",
        active
          ? "bg-accent text-accent-foreground font-medium"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {label}
      {active && <ChevronRight className="ml-auto h-3.5 w-3.5" />}
    </button>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Settings() {
  const [activeSection, setActiveSection] = useState<Section>("startup");
  const queryClient = useQueryClient();

  const {
    data: settings,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const mutation = useMutation({
    mutationFn: saveSettings,
    onSuccess: () => {
      toast.success("Configuration locked");
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: () => toast.error("Failed to save settings"),
  });

  const handleSave = async (patch: Partial<SettingsResponse>) => {
    const merged = { ...(settings ?? {}), ...patch };
    await mutation.mutateAsync(merged as Partial<SettingsResponse>);
  };

  return (
    <div className="flex h-full">
      {/* Sidebar */}
      <aside className="w-52 shrink-0 border-r p-3">
        <div className="mb-3 px-3 py-1">
          <div className="flex items-center gap-2">
            <SettingsIcon className="h-4 w-4" />
            <span className="text-sm font-semibold">Settings</span>
          </div>
        </div>
        <nav className="space-y-0.5">
          <SidebarItem
            label="Startup"
            icon={Activity}
            active={activeSection === "startup"}
            onClick={() => setActiveSection("startup")}
          />
          <SidebarItem
            label="Model"
            icon={Bot}
            active={activeSection === "model"}
            onClick={() => setActiveSection("model")}
          />
          <SidebarItem
            label="MCP Servers"
            icon={Server}
            active={activeSection === "mcp"}
            onClick={() => setActiveSection("mcp")}
          />
          <SidebarItem
            label="Monitoring"
            icon={Eye}
            active={activeSection === "monitoring"}
            onClick={() => setActiveSection("monitoring")}
          />
        </nav>
      </aside>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {activeSection === "monitoring" ? (
          <Monitoring />
        ) : (
          <div className="p-8">
            <div className="mx-auto max-w-2xl">
              {isLoading ? (
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading settings...
                </div>
              ) : error ? (
                <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
                  Failed to load settings. Check that the backend is running.
                </div>
              ) : settings ? (
                <>
                  {activeSection === "startup" && <StartupSection settings={settings} />}
                  {activeSection === "model" && (
                    <ModelSection settings={settings} onSave={handleSave} />
                  )}
                  {activeSection === "mcp" && (
                    <>
                      <Separator className="mb-6" />
                      <MCPSection settings={settings} onSave={handleSave} />
                    </>
                  )}
                </>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
