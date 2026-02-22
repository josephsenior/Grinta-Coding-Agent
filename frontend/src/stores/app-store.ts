import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "dark" | "light";

export interface AppState {
  theme: Theme;
  sidebarOpen: boolean;
  contextPanelOpen: boolean;

  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setSidebarOpen: (open: boolean) => void;
  setContextPanelOpen: (open: boolean) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      theme: "dark",
      sidebarOpen: true,
      contextPanelOpen: true,

      setTheme: (theme) => {
        document.documentElement.classList.toggle("dark", theme === "dark");
        set({ theme });
      },

      toggleTheme: () =>
        set((state) => {
          const next = state.theme === "dark" ? "light" : "dark";
          document.documentElement.classList.toggle("dark", next === "dark");
          return { theme: next };
        }),

      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      setContextPanelOpen: (open) => set({ contextPanelOpen: open }),
    }),
    {
      name: "forge-app-store",
      partialize: (state) => ({ theme: state.theme }),
    },
  ),
);
