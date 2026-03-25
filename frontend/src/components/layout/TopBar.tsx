import { Settings, Sun, Moon, BookOpen, Plus, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";
import { useEffect } from "react";
import { useBackendHealth } from "@/hooks/use-backend-health";
import { useNewConversation } from "@/hooks/use-new-conversation";
import { useAppStore } from "@/stores/app-store";

/** Compact primary actions: light = high-contrast pill; dark = soft card surface (no pure white). */
function topNavPill(active?: boolean) {
  return cn(
    "h-7 shrink-0 gap-1 rounded-md border px-2 text-xs font-medium shadow-sm transition-colors",
    "border-transparent bg-neutral-950 text-white hover:bg-neutral-800 hover:text-white",
    "dark:border-border/55 dark:bg-card dark:text-foreground dark:shadow-none dark:hover:bg-muted dark:hover:text-foreground",
    "[&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-current",
    active && "ring-1 ring-primary/50 ring-offset-1 ring-offset-background dark:ring-offset-background",
  );
}

function formatUptime(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function TopBar() {
  const { theme, toggleTheme } = useTheme();
  const { connected, uptime_seconds } = useBackendHealth();
  const { create: handleCreate, isPending: isCreating } = useNewConversation();
  const settingsWindowOpen = useAppStore((s) => s.settingsWindowOpen);
  const setSettingsWindowOpen = useAppStore((s) => s.setSettingsWindowOpen);
  const knowledgeWindowOpen = useAppStore((s) => s.knowledgeWindowOpen);
  const setKnowledgeWindowOpen = useAppStore((s) => s.setKnowledgeWindowOpen);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "n") {
        e.preventDefault();
        handleCreate();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleCreate]);

  return (
    <>
      <header className="flex h-12 shrink-0 items-center justify-between border-b px-4">
        <nav className="flex min-w-0 flex-1 items-center gap-2" aria-label="Main">
          <div className="flex items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setKnowledgeWindowOpen(true)}
                  className={topNavPill(knowledgeWindowOpen)}
                >
                  <BookOpen className="shrink-0" />
                  <span className="hidden md:inline">Knowledge</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>Knowledge base</TooltipContent>
            </Tooltip>

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleCreate}
                  disabled={isCreating}
                  className={topNavPill(false)}
                >
                  {isCreating ? (
                    <Loader2 className="shrink-0 animate-spin" />
                  ) : (
                    <Plus className="shrink-0" />
                  )}
                  <span className="hidden sm:inline">New</span>
                </Button>
              </TooltipTrigger>
              <TooltipContent>New Conversation (Ctrl+N)</TooltipContent>
            </Tooltip>
          </div>
        </nav>

        <div className="flex items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex h-7 w-7 items-center justify-center cursor-default">
                <span
                  className={cn(
                    "h-2 w-2 rounded-full transition-colors",
                    connected === null
                      ? "bg-yellow-400 animate-pulse"
                      : connected
                        ? "bg-green-500"
                        : "bg-red-500",
                  )}
                />
              </span>
            </TooltipTrigger>
            <TooltipContent>
              {connected === null
                ? "Connecting to backend…"
                : connected
                  ? `Backend · ${uptime_seconds != null ? formatUptime(uptime_seconds) + " uptime" : "connected"}`
                  : "Backend unreachable"}
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={toggleTheme}>
                {theme === "dark" ? (
                  <Sun className="h-3.5 w-3.5" />
                ) : (
                  <Moon className="h-3.5 w-3.5" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>Toggle theme</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSettingsWindowOpen(true)}
                className={cn(
                  "h-7 gap-1.5 px-2 text-xs text-muted-foreground",
                  settingsWindowOpen && "bg-accent text-accent-foreground",
                )}
              >
                <Settings className="h-3.5 w-3.5 shrink-0" />
                <span className="hidden md:inline">Settings</span>
              </Button>
            </TooltipTrigger>
            <TooltipContent>Settings</TooltipContent>
          </Tooltip>
        </div>
      </header>
    </>
  );
}
