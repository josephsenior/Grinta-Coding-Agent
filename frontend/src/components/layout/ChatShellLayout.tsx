import { useCallback, useEffect, useState } from "react";
import { Outlet, useMatch } from "react-router-dom";
import { ConversationSidebar } from "./ConversationSidebar";
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel";
import { useAppStore } from "@/stores/app-store";
import { useColumnResize } from "@/hooks/use-column-resize";

const SIDEBAR_KEY = "forge-layout-sidebar-w";
const WORKSPACE_KEY = "forge-layout-workspace-w";
const DEFAULT_SIDEBAR = 300;
const DEFAULT_WORKSPACE = 380;
const SIDEBAR_MIN = 240;
const SIDEBAR_MAX = 440;

function readStoredWidth(key: string, fallback: number): number {
  try {
    const v = localStorage.getItem(key);
    if (v == null) return fallback;
    const n = Number.parseInt(v, 10);
    return Number.isFinite(n) ? n : fallback;
  } catch {
    return fallback;
  }
}

export function ChatShellLayout() {
  const match = useMatch("/chat/:id");
  const conversationId = match?.params.id ?? null;

  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const contextPanelOpen = useAppStore((s) => s.contextPanelOpen);

  const [sidebarWidth, setSidebarWidth] = useState(() => {
    const w = readStoredWidth(SIDEBAR_KEY, DEFAULT_SIDEBAR);
    return Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, w));
  });
  const [workspaceWidth, setWorkspaceWidth] = useState(() =>
    readStoredWidth(WORKSPACE_KEY, DEFAULT_WORKSPACE),
  );

  useEffect(() => {
    localStorage.setItem(SIDEBAR_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  useEffect(() => {
    localStorage.setItem(WORKSPACE_KEY, String(workspaceWidth));
  }, [workspaceWidth]);

  const resizeLeft = useColumnResize({ min: SIDEBAR_MIN, max: SIDEBAR_MAX, invertDelta: true });
  const resizeRight = useColumnResize({ min: 280, max: 720, invertDelta: false });

  const onResizeLeft = useCallback(
    (e: React.MouseEvent) => {
      resizeLeft(e, sidebarWidth, setSidebarWidth);
    },
    [resizeLeft, sidebarWidth],
  );

  const onResizeRight = useCallback(
    (e: React.MouseEvent) => {
      resizeRight(e, workspaceWidth, setWorkspaceWidth);
    },
    [resizeRight, workspaceWidth],
  );

  const showWorkspace = contextPanelOpen && !!conversationId;

  return (
    <div className="flex h-full min-h-0 flex-1 overflow-hidden">
      {sidebarOpen && (
        <>
          <div
            className="flex h-full min-h-0 shrink-0 flex-col overflow-hidden border-r bg-background"
            style={{ width: sidebarWidth }}
          >
            <ConversationSidebar />
          </div>
          <div
            role="separator"
            aria-orientation="vertical"
            className="w-1 shrink-0 cursor-col-resize hover:bg-primary/40 active:bg-primary/60"
            onMouseDown={onResizeLeft}
          />
        </>
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </div>

      {showWorkspace && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            className="w-1 shrink-0 cursor-col-resize hover:bg-primary/40 active:bg-primary/60"
            onMouseDown={onResizeRight}
          />
          <div
            className="flex h-full min-h-0 shrink-0 flex-col overflow-hidden border-l bg-background"
            style={{ width: workspaceWidth }}
          >
            <WorkspacePanel conversationId={conversationId} />
          </div>
        </>
      )}
    </div>
  );
}
