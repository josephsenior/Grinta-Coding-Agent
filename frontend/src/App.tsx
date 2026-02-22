import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "sonner";
import { Layout } from "@/components/layout/Layout";
import Home from "@/pages/Home";
import Chat from "@/pages/Chat";
import Settings from "@/pages/Settings";
import KnowledgeBase from "@/pages/KnowledgeBase";
import Memory from "@/pages/Memory";
import Monitoring from "@/pages/Monitoring";
import { useEffect } from "react";
import { useAppStore } from "@/stores/app-store";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
});

function ThemeInitializer() {
  const theme = useAppStore((s) => s.theme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  return null;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <BrowserRouter>
          <ThemeInitializer />
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<Home />} />
              <Route path="/chat/:id" element={<Chat />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/knowledge" element={<KnowledgeBase />} />
              <Route path="/memory" element={<Memory />} />
              <Route path="/monitoring" element={<Monitoring />} />
            </Route>
          </Routes>
          <Toaster richColors position="bottom-right" />
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
