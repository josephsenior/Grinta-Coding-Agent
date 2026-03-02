import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

export type ContextTab = "editor" | "terminal" | "diff" | "preview";

export interface ContextPanelState {
  activeTab: ContextTab;
  // Editor state
  editorFilePath: string | null;
  editorContent: string | null;
  editorLanguage: string;
  editorReadOnly: boolean;
  // Diff state
  diffFilePath: string | null;
  diffContent: string | null;
  // Terminal state
  terminalLines: string[];
  // Preview state
  previewUrl: string | null;

  // Actions
  setActiveTab: (tab: ContextTab) => void;
  openFile: (path: string, content: string) => void;
  openDiff: (path: string, diff: string) => void;
  appendTerminalOutput: (text: string) => void;
  clearTerminal: () => void;
  setPreviewUrl: (url: string | null) => void;
  setEditorReadOnly: (readOnly: boolean) => void;
  resetPanel: () => void;
}

/** Infer Monaco language from file path extension. */
function inferLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    py: "python",
    rs: "rust",
    go: "go",
    java: "java",
    rb: "ruby",
    sh: "shell",
    bash: "shell",
    zsh: "shell",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    toml: "toml",
    md: "markdown",
    html: "html",
    css: "css",
    scss: "scss",
    sql: "sql",
    xml: "xml",
    dockerfile: "dockerfile",
    c: "c",
    cpp: "cpp",
    h: "c",
    hpp: "cpp",
    cs: "csharp",
    swift: "swift",
    kt: "kotlin",
    php: "php",
    lua: "lua",
    r: "r",
  };
  return map[ext] || "plaintext";
}

export const useContextPanelStore = create<ContextPanelState>()(
  immer((set) => ({
    activeTab: "editor",
    editorFilePath: null,
    editorContent: null,
    editorLanguage: "plaintext",
    editorReadOnly: true,
    diffFilePath: null,
    diffContent: null,
    terminalLines: [],
    previewUrl: null,

    setActiveTab: (tab) =>
      set((state) => {
        state.activeTab = tab;
      }),

    openFile: (path, content) =>
      set((state) => {
        state.editorFilePath = path;
        state.editorContent = content;
        state.editorLanguage = inferLanguage(path);
        state.editorReadOnly = true;
        state.activeTab = "editor";
      }),

    openDiff: (path, diff) =>
      set((state) => {
        state.diffFilePath = path;
        state.diffContent = diff;
        state.activeTab = "diff";
      }),

    appendTerminalOutput: (text) =>
      set((state) => {
        state.terminalLines.push(text);
        // Cap at 5000 lines
        if (state.terminalLines.length > 5000) {
          state.terminalLines = state.terminalLines.slice(-4000);
        }
      }),

    clearTerminal: () =>
      set((state) => {
        state.terminalLines = [];
      }),

    setPreviewUrl: (url) =>
      set((state) => {
        state.previewUrl = url;
        if (url) state.activeTab = "preview";
      }),

    setEditorReadOnly: (readOnly) =>
      set((state) => {
        state.editorReadOnly = readOnly;
      }),

    /** Reset all panel state — call on conversation change to prevent data leaking. */
    resetPanel: () =>
      set((state) => {
        state.activeTab = "editor";
        state.editorFilePath = null;
        state.editorContent = null;
        state.editorLanguage = "plaintext";
        state.editorReadOnly = true;
        state.diffFilePath = null;
        state.diffContent = null;
        state.terminalLines = [];
        state.previewUrl = null;
      }),
  })),
);
