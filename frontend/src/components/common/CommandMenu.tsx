import { useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "cmdk";
import { Hammer, Settings, BookOpen, Brain, Activity, MessageSquare } from "lucide-react";
import { useConversations } from "@/hooks/use-conversations";
import { cn } from "@/lib/utils";

interface CommandMenuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandMenu({ open, onOpenChange }: CommandMenuProps) {
  const navigate = useNavigate();
  const { data } = useConversations();

  // Keyboard shortcut: Ctrl+K
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    },
    [open, onOpenChange],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const runCommand = (command: () => void) => {
    onOpenChange(false);
    command();
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      label="Global Command Menu"
    >
      <CommandInput placeholder="Search conversations, pages..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Pages">
          <CommandItem onSelect={() => runCommand(() => navigate("/"))}>
            <Hammer className={cn("mr-2 h-4 w-4")} />
            Home
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => navigate("/settings"))}>
            <Settings className={cn("mr-2 h-4 w-4")} />
            Settings
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => navigate("/knowledge"))}>
            <BookOpen className={cn("mr-2 h-4 w-4")} />
            Knowledge Base
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => navigate("/memory"))}>
            <Brain className={cn("mr-2 h-4 w-4")} />
            Memory
          </CommandItem>
          <CommandItem onSelect={() => runCommand(() => navigate("/monitoring"))}>
            <Activity className={cn("mr-2 h-4 w-4")} />
            Monitoring
          </CommandItem>
        </CommandGroup>

        {data?.results && data.results.length > 0 && (
          <CommandGroup heading="Conversations">
            {data.results.slice(0, 10).map((conv) => (
              <CommandItem
                key={conv.conversation_id}
                onSelect={() =>
                  runCommand(() => navigate(`/chat/${conv.conversation_id}`))
                }
              >
                <MessageSquare className={cn("mr-2 h-4 w-4")} />
                {conv.title || "Untitled"}
              </CommandItem>
            ))}
          </CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
