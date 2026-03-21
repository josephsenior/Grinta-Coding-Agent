import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, useLayoutEffect } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "@/lib/query-client";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "sonner";
import { Layout } from "@/components/layout/Layout";
import { ChatShellLayout } from "@/components/layout/ChatShellLayout";
import Home from "@/pages/Home";
import Chat from "@/pages/Chat";
import { useAppStore } from "@/stores/app-store";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function ThemeInitializer() {
  const theme = useAppStore((s) => s.theme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  return null;
}

/** Old bookmarks to /settings or /knowledge open the overlay then land on home. */
function OpenWindowRedirect({ kind }: { kind: "settings" | "knowledge" }) {
  const setSettings = useAppStore((s) => s.setSettingsWindowOpen);
  const setKnowledge = useAppStore((s) => s.setKnowledgeWindowOpen);
  useLayoutEffect(() => {
    if (kind === "settings") setSettings(true);
    else setKnowledge(true);
  }, [kind, setKnowledge, setSettings]);
  return <Navigate to="/" replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <BrowserRouter>
          <ThemeInitializer />
          <ErrorBoundary>
            <Routes>
              <Route element={<Layout />}>
                <Route element={<ChatShellLayout />}>
                  <Route path="/" element={<Home />} />
                  <Route path="/chat/:id" element={<Chat />} />
                </Route>
                <Route path="/settings" element={<OpenWindowRedirect kind="settings" />} />
                <Route path="/knowledge" element={<OpenWindowRedirect kind="knowledge" />} />
              </Route>
            </Routes>
          </ErrorBoundary>
          <Toaster richColors position="bottom-right" />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
