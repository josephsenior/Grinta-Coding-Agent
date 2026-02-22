import { useAppStore } from "@/stores/app-store";

export function useTheme() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const toggleTheme = useAppStore((s) => s.toggleTheme);
  return { theme, setTheme, toggleTheme };
}
