import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { inferMonacoLanguage } from "@/lib/monaco-language";

export type WorkspaceView = "browse" | "editor" | "diff";

export interface ContextPanelState {
  /** browse = file tree + changes; editor / diff = full-height viewer */
  workspaceView: WorkspaceView;
  // Editor state
  editorFilePath: string | null;
  editorContent: string | null;
  editorLanguage: string;
  editorReadOnly: boolean;
  // Diff state
  diffFilePath: string | null;
  diffContent: string | null;
  // Legacy terminal buffer (optional; no dedicated tab)
  terminalLines: string[];
  previewUrl: string | null;

  setWorkspaceView: (view: WorkspaceView) => void;
  goToBrowse: () => void;
  openFile: (path: string, content: string) => void;
  openDiff: (path: string, diff: string) => void;
  appendTerminalOutput: (text: string) => void;
  appendTerminalOutputBatch: (lines: string[]) => void;
  clearTerminal: () => void;
  setPreviewUrl: (url: string | null) => void;
  setEditorReadOnly: (readOnly: boolean) => void;
  resetPanel: () => void;
}

export const useContextPanelStore = create<ContextPanelState>()(
  immer((set) => ({
    workspaceView: "browse",
    editorFilePath: null,
    editorContent: null,
    editorLanguage: "plaintext",
    editorReadOnly: true,
    diffFilePath: null,
    diffContent: null,
    terminalLines: [],
    previewUrl: null,

    setWorkspaceView: (view) =>
      set((state) => {
        state.workspaceView = view;
      }),

    goToBrowse: () =>
      set((state) => {
        state.workspaceView = "browse";
      }),

    openFile: (path, content) =>
      set((state) => {
        state.editorFilePath = path;
        state.editorContent = content;
        state.editorLanguage = inferMonacoLanguage(path);
        state.editorReadOnly = true;
        state.workspaceView = "editor";
      }),

    openDiff: (path, diff) =>
      set((state) => {
        state.diffFilePath = path;
        state.diffContent = diff;
        state.workspaceView = "diff";
      }),

    appendTerminalOutput: (text) =>
      set((state) => {
        state.terminalLines.push(text);
        if (state.terminalLines.length > 5000) {
          state.terminalLines = state.terminalLines.slice(-4000);
        }
      }),

    appendTerminalOutputBatch: (lines) =>
      set((state) => {
        if (!Array.isArray(lines) || lines.length === 0) return;
        state.terminalLines.push(...lines);
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
      }),

    setEditorReadOnly: (readOnly) =>
      set((state) => {
        state.editorReadOnly = readOnly;
      }),

    resetPanel: () =>
      set((state) => {
        state.workspaceView = "browse";
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
