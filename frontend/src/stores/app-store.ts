import { create } from "zustand";
import { persist } from "zustand/middleware";

export type Theme = "dark" | "light";

export interface AppState {
  theme: Theme;
  sidebarOpen: boolean;
  contextPanelOpen: boolean;
  /** Global command palette (Ctrl+K); opened from chat sidebar or keyboard. */
  commandMenuOpen: boolean;
  settingsWindowOpen: boolean;
  knowledgeWindowOpen: boolean;

  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setSidebarOpen: (open: boolean) => void;
  setContextPanelOpen: (open: boolean) => void;
  setCommandMenuOpen: (open: boolean) => void;
  setSettingsWindowOpen: (open: boolean) => void;
  setKnowledgeWindowOpen: (open: boolean) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      theme: "dark",
      sidebarOpen: true,
      contextPanelOpen: true,
      commandMenuOpen: false,
      settingsWindowOpen: false,
      knowledgeWindowOpen: false,

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
      setCommandMenuOpen: (open) => set({ commandMenuOpen: open }),
      setSettingsWindowOpen: (open) => set({ settingsWindowOpen: open }),
      setKnowledgeWindowOpen: (open) => set({ knowledgeWindowOpen: open }),
    }),
    {
      name: "forge-app-store",
      partialize: (state) => ({ theme: state.theme }),
    },
  ),
);
