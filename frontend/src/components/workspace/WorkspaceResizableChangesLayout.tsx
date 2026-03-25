import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { useWorkspaceChangesFraction } from "@/hooks/use-workspace-changes-fraction";

interface WorkspaceResizableChangesLayoutProps {
  storageKey: string;
  top: ReactNode;
  bottom: ReactNode;
  topClassName?: string;
}

/** Vertical split: flexible top, draggable separator, changes band (20–40% of height, persisted). */
export function WorkspaceResizableChangesLayout({
  storageKey,
  top,
  bottom,
  topClassName,
}: WorkspaceResizableChangesLayoutProps) {
  const { containerRef, changesFrac, onSeparatorPointerDown } = useWorkspaceChangesFraction(storageKey);
  const pct = Math.round(changesFrac * 100);

  return (
    <div
      ref={containerRef}
      className="grid h-full min-h-0 w-full"
      style={{ gridTemplateRows: `minmax(0, 1fr) 4px ${changesFrac * 100}%` }}
    >
      <div className={cn("min-h-0 min-w-0 overflow-hidden", topClassName)}>{top}</div>
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-valuenow={pct}
        aria-valuemin={20}
        aria-valuemax={40}
        aria-label="Resize changes section"
        className="z-10 -my-px h-1 shrink-0 cursor-row-resize touch-none border-y border-transparent hover:border-primary/30 hover:bg-primary/20 active:bg-primary/35"
        onPointerDown={onSeparatorPointerDown}
      />
      <div className="flex min-h-0 min-w-0 flex-col overflow-hidden">{bottom}</div>
    </div>
  );
}
