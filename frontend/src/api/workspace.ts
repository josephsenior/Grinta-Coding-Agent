import apiClient from "./client";

export interface WorkspaceInfo {
  /** Absolute project folder, or null until the user opens a workspace. */
  path: string | null;
}

export async function getWorkspace(): Promise<WorkspaceInfo> {
  const { data } = await apiClient.get<WorkspaceInfo>("/workspace");
  return data;
}

export async function setWorkspacePath(path: string): Promise<WorkspaceInfo & { ok: boolean }> {
  const { data } = await apiClient.post<WorkspaceInfo & { ok: boolean }>("/workspace", {
    path,
  });
  return data;
}

export async function createWorkspaceFolder(
  parent_path: string,
  name: string,
): Promise<WorkspaceInfo & { ok: boolean }> {
  const { data } = await apiClient.post<WorkspaceInfo & { ok: boolean }>(
    "/workspace/create",
    { parent_path, name },
  );
  return data;
}
