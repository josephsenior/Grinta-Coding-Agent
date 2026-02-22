import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";
import { Toaster } from "sonner";
import { NewConversationDialog } from "@/components/common/NewConversationDialog";
import { useAppStore } from "@/stores/app-store";

export function Layout() {
  const newConvOpen = useAppStore((s) => s.newConvOpen);
  const setNewConvOpen = useAppStore((s) => s.setNewConvOpen);
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <TopBar />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
      <NewConversationDialog open={newConvOpen} onOpenChange={setNewConvOpen} />
      <Toaster richColors position="bottom-right" />
    </div>
  );
}
