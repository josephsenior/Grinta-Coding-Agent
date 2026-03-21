import { Hammer, Plus, Loader2, PanelLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useNewConversation } from "@/hooks/use-new-conversation";
import { useAppStore } from "@/stores/app-store";

/**
 * Center column empty state when no chat is selected (sidebar shows conversations).
 */
export default function Home() {
  const { create: handleCreate, isPending: isCreating } = useNewConversation();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen);

  return (
    <div className="flex h-full flex-col">
      {!sidebarOpen && (
        <div className="flex min-h-12 shrink-0 items-center border-b border-border/50 bg-background/90 px-4 py-1.5 backdrop-blur-sm">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => setSidebarOpen(true)}
                aria-label="Show conversation list"
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Show conversation list</TooltipContent>
          </Tooltip>
        </div>
      )}
      <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6 pb-8 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
        <Hammer className="h-8 w-8 text-primary" />
      </div>
      <div className="max-w-sm space-y-2">
        <h1 className="text-xl font-semibold tracking-tight">Forge</h1>
        <p className="text-sm text-muted-foreground leading-relaxed">
          Select a conversation from the sidebar or start a new one. The workspace panel opens when
          a chat is active.
        </p>
      </div>
      <Button onClick={handleCreate} disabled={isCreating} size="lg" className="gap-2">
        {isCreating ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Plus className="h-4 w-4" />
        )}
        New conversation
      </Button>
      </div>
    </div>
  );
}
