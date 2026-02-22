import { Link, useLocation } from "react-router-dom";
import {
  Hammer,
  Settings,
  Sun,
  Moon,
  Search,
  Activity,
  BookOpen,
  Brain,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { CommandMenu } from "@/components/common/CommandMenu";

const navItems = [
  { to: "/", icon: Hammer, label: "Home" },
  { to: "/knowledge", icon: BookOpen, label: "Knowledge" },
  { to: "/memory", icon: Brain, label: "Memory" },
  { to: "/monitoring", icon: Activity, label: "Monitoring" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export function TopBar() {
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();
  const [commandOpen, setCommandOpen] = useState(false);

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

        {/* Right: Search + Theme */}
        <div className="flex items-center gap-1">
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
        </div>
      </header>

      <CommandMenu open={commandOpen} onOpenChange={setCommandOpen} />
    </>
  );
}
