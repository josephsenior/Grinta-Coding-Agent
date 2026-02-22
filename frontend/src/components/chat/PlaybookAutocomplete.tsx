import { useMemo } from "react";
import { BookOpen } from "lucide-react";
import type { Playbook } from "@/api/playbooks";

interface PlaybookAutocompleteProps {
  playbooks: Playbook[];
  filter: string; // The text after / in the input
  onSelect: (playbook: Playbook) => void;
}

export function PlaybookAutocomplete({
  playbooks,
  filter,
  onSelect,
}: PlaybookAutocompleteProps) {
  const filtered = useMemo(() => {
    const lower = filter.toLowerCase();
    return playbooks.filter(
      (p) =>
        p.name.toLowerCase().includes(lower) ||
        (p.description?.toLowerCase().includes(lower) ?? false),
    );
  }, [playbooks, filter]);

  if (filtered.length === 0) return null;

  return (
    <div className="absolute bottom-full left-0 right-0 mb-1 max-h-48 overflow-auto rounded-lg border bg-popover shadow-lg">
      {filtered.map((pb) => (
        <button
          key={pb.name}
          type="button"
          className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-accent transition-colors"
          onMouseDown={(e) => {
            // Use mouseDown instead of click to fire before textarea blur
            e.preventDefault();
            onSelect(pb);
          }}
        >
          <BookOpen className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <div className="min-w-0">
            <div className="font-medium">/{pb.name}</div>
            {pb.description && (
              <div className="truncate text-xs text-muted-foreground">
                {pb.description}
              </div>
            )}
          </div>
        </button>
      ))}
    </div>
  );
}
