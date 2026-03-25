import apiClient from "./client";

/** Best-effort path for the agent: upload API may return absolute paths; workspace tools expect a simple relative name for root uploads. */
export function agentPathFromUploadResponse(uploadedPath: string): string {
  const normalized = uploadedPath.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts.length > 0 ? (parts[parts.length - 1] as string) : uploadedPath;
}

/** List files at a path in the conversation workspace. */
export async function listFiles(
  conversationId: string,
  path?: string,
  options?: { recursive?: boolean },
): Promise<string[]> {
  const params: Record<string, string | boolean> = {};
  if (path) params.path = path;
  if (options?.recursive) params.recursive = true;
  const { data } = await apiClient.get<string[]>(
    `/conversations/${conversationId}/files/list-files`,
    { params },
  );
  return data;
}

/** Get the content of a specific file. */
export async function getFileContent(
  conversationId: string,
  filePath: string,
): Promise<string> {
  const { data } = await apiClient.get<{ code: string }>(
    `/conversations/${conversationId}/files/select-file`,
    { params: { file: filePath } },
  );
  return data.code;
}

/** Get git changes for a conversation workspace. */
export async function getGitChanges(
  conversationId: string,
): Promise<Array<{ path: string; status: string }>> {
  const { data } = await apiClient.get(
    `/conversations/${conversationId}/files/git/changes`,
  );
  return data;
}

/** Get git diff for a specific file. */
export async function getGitDiff(
  conversationId: string,
  path: string,
): Promise<string> {
  const { data } = await apiClient.get(
    `/conversations/${conversationId}/files/git/diff`,
    { params: { path } },
  );
  return typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

/** Get web host URLs for the conversation runtime. */
export async function getWebHosts(
  conversationId: string,
): Promise<string[]> {
  const { data } = await apiClient.get<{ hosts: string[] }>(
    `/conversations/${conversationId}/web-hosts`,
  );
  return data.hosts;
}

/** Upload files to the conversation workspace. */
export async function uploadFiles(
  conversationId: string,
  files: File[],
): Promise<{ uploaded_files: string[]; skipped_files: Array<{ name: string; reason: string }> }> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const { data } = await apiClient.post(
    `/conversations/${conversationId}/files/upload-files`,
    formData,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return data;
}

/** Download the workspace as a zip file. */
export function getWorkspaceZipUrl(conversationId: string): string {
  return `/api/v1/conversations/${conversationId}/files/zip-directory`;
}
