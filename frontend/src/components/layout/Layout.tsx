import { Outlet } from "react-router-dom";
import { CommandMenu } from "@/components/common/CommandMenu";
import { AppAuxWindows } from "./AppAuxWindows";
import { TopBar } from "./TopBar";

export function Layout() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <TopBar />
      <CommandMenu />
      <AppAuxWindows />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
