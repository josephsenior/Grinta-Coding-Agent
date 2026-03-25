import { useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "cmdk";
import { Settings, BookOpen, Activity, MessageSquare, Plus } from "lucide-react";
import { useConversations } from "@/hooks/use-conversations";
import { useNewConversation } from "@/hooks/use-new-conversation";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/app-store";
import { CMDK_CONTENT, CMDK_OVERLAY, CMDK_ROOT } from "@/components/common/cmdk-palette-classes";

export function CommandMenu() {
  const navigate = useNavigate();
  const open = useAppStore((s) => s.commandMenuOpen);
  const setOpen = useAppStore((s) => s.setCommandMenuOpen);
  const setSettingsWindowOpen = useAppStore((s) => s.setSettingsWindowOpen);
  const setKnowledgeWindowOpen = useAppStore((s) => s.setKnowledgeWindowOpen);
  const { data } = useConversations();
  const { create: handleCreate } = useNewConversation();

  // Keyboard shortcut: Ctrl+K
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setOpen(!open);
      }
    },
    [open, setOpen],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const runCommand = (command: () => void) => {
    setOpen(false);
    command();
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      label="Global Command Menu"
      overlayClassName={CMDK_OVERLAY}
      contentClassName={CMDK_CONTENT}
      className={CMDK_ROOT}
    >
      <CommandInput placeholder="Search conversations, pages…" />
      <CommandList className="max-h-[min(55vh,400px)] min-h-0 overflow-x-hidden overflow-y-auto">
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Actions">
          <CommandItem onSelect={() => runCommand(handleCreate)}>
            <Plus className="mr-2 h-4 w-4" />
            New Conversation
            <span className="ml-auto text-xs text-muted-foreground">Ctrl+N</span>
          </CommandItem>
        </CommandGroup>

        <CommandGroup heading="Windows">
          <CommandItem
            onSelect={() =>
              runCommand(() => {
                setKnowledgeWindowOpen(true);
              })
            }
          >
            <BookOpen className={cn("mr-2 h-4 w-4")} />
            Knowledge base
          </CommandItem>
          <CommandItem
            onSelect={() =>
              runCommand(() => {
                setSettingsWindowOpen(true);
              })
            }
          >
            <Settings className={cn("mr-2 h-4 w-4")} />
            Settings
          </CommandItem>
          <CommandItem
            onSelect={() =>
              runCommand(() => {
                setSettingsWindowOpen(true);
              })
            }
          >
            <Activity className={cn("mr-2 h-4 w-4")} />
            Monitoring
            <span className="ml-auto text-xs text-muted-foreground">in Settings</span>
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
