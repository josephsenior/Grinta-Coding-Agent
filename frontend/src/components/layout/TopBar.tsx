import { Link, useLocation } from "react-router-dom";
import { Hammer, Settings, Sun, Moon, Search, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";
import { useState, useEffect } from "react";
import { CommandMenu } from "@/components/common/CommandMenu";
import { useBackendHealth } from "@/hooks/use-backend-health";
import { useAppStore } from "@/stores/app-store";

const navItems = [
  { to: "/", icon: Hammer, label: "Home" },
  { to: "/knowledge", icon: BookOpen, label: "Knowledge" },
];

function formatUptime(s: number): string {
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function TopBar() {
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();
  const [commandOpen, setCommandOpen] = useState(false);
  const setNewConvOpen = useAppStore((s) => s.setNewConvOpen);
  const { connected, uptime_seconds } = useBackendHealth();

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "n") {
        e.preventDefault();
        setNewConvOpen(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [setNewConvOpen]);

  return (
    <>
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
        {/* Left: Logo + Nav */}
        <div className="flex items-center gap-1">
          <Link
            to="/"
            className="mr-4 flex items-center gap-2 font-bold text-lg"
          >
            <Hammer className="h-5 w-5 text-primary" />
            <span>Forge</span>
          </Link>

          <nav className="flex items-center gap-0.5">
            {navItems.map(({ to, icon: Icon, label }) => (
              <Tooltip key={to}>
                <TooltipTrigger asChild>
                  <Link
                    to={to}
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors hover:bg-accent hover:text-accent-foreground",
                      location.pathname === to
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground",
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="hidden md:inline">{label}</span>
                  </Link>
                </TooltipTrigger>
                <TooltipContent>{label}</TooltipContent>
              </Tooltip>
            ))}
          </nav>
        </div>

        {/* Right: Status + Search + Theme + Settings */}
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex h-8 w-8 items-center justify-center cursor-default">
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
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setCommandOpen(true)}
              >
                <Search className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Search (Ctrl+K)</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" onClick={toggleTheme}>
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>Toggle theme</TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <Link
                to="/settings"
                className={cn(
                  "inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors hover:bg-accent hover:text-accent-foreground",
                  location.pathname.startsWith("/settings")
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground",
                )}
              >
                <Settings className="h-4 w-4" />
              </Link>
            </TooltipTrigger>
            <TooltipContent>Settings</TooltipContent>
          </Tooltip>
        </div>
      </header>

      <CommandMenu open={commandOpen} onOpenChange={setCommandOpen} />
    </>
  );
}
