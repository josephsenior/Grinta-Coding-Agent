import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useAppStore } from "@/stores/app-store";
import { cn } from "@/lib/utils";
import Settings from "@/pages/Settings";
import KnowledgeBase from "@/pages/KnowledgeBase";

/** Overrides default dialog sizing so Settings / Knowledge feel like app windows. */
const overlayContentClass =
  "flex h-[min(90dvh,56rem)] w-[min(56rem,calc(100vw-1.5rem))] max-w-none flex-col gap-0 overflow-hidden p-0";

/**
 * Full settings and knowledge UIs as modal windows over the single main shell.
 */
export function AppAuxWindows() {
  const settingsOpen = useAppStore((s) => s.settingsWindowOpen);
  const setSettingsOpen = useAppStore((s) => s.setSettingsWindowOpen);
  const knowledgeOpen = useAppStore((s) => s.knowledgeWindowOpen);
  const setKnowledgeOpen = useAppStore((s) => s.setKnowledgeWindowOpen);

  return (
    <>
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className={cn(overlayContentClass)}>
          <div className="min-h-0 flex-1 overflow-hidden">
            <Settings />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={knowledgeOpen} onOpenChange={setKnowledgeOpen}>
        <DialogContent className={cn(overlayContentClass)}>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <KnowledgeBase />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
