import { BookOpen, Play, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { usePlaybooks } from "@/hooks/use-playbooks";
import { sendUserAction } from "@/socket/client";
import { toast } from "sonner";

interface PlaybooksTabProps {
  conversationId: string;
}

export function PlaybooksTab({ conversationId }: PlaybooksTabProps) {
  const { data: playbooks = [], isLoading } = usePlaybooks(conversationId);

  const handleRun = (name: string) => {
    sendUserAction({
      action: "message",
      args: { content: `/${name}` },
    });
    toast.success(`Running playbook: ${name}`);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b px-3 py-2">
        <BookOpen className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
          Playbooks
        </span>
        {playbooks.length > 0 && (
          <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
            {playbooks.length}
          </Badge>
        )}
      </div>
      <ScrollArea className="flex-1">
        <div className="p-2 space-y-1">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : playbooks.length === 0 ? (
            <p className="px-2 py-4 text-xs text-muted-foreground">
              No playbooks available
            </p>
          ) : (
            playbooks.map((pb) => (
              <div
                key={pb.name}
                className="flex items-start gap-2 rounded-lg border p-2 hover:bg-accent transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium font-mono">/{pb.name}</span>
                    {pb.type && (
                      <Badge variant="outline" className="h-4 px-1 text-[10px]">
                        {pb.type}
                      </Badge>
                    )}
                  </div>
                  {pb.description && (
                    <p className="mt-0.5 text-[11px] text-muted-foreground line-clamp-2">
                      {pb.description}
                    </p>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0"
                  onClick={() => handleRun(pb.name)}
                  title={`Run /${pb.name}`}
                >
                  <Play className="h-3 w-3" />
                </Button>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  );
}
