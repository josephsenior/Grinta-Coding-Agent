import { Outlet } from "react-router-dom";
import { TopBar } from "./TopBar";

export function Layout() {
  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <TopBar />
      <main className="flex-1 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
