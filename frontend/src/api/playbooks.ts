import apiClient from "./client";

export interface Playbook {
  name: string;
  description?: string;
  type?: string;
  /** Full markdown/body (from API). */
  content?: string;
  /** Filesystem source path; empty if not workspace-backed. */
  source?: string;
  triggers?: string[];
  inputs?: unknown[];
  tools?: string[];
}

interface PlaybooksResponse {
  playbooks: Playbook[];
}

export async function getPlaybooks(conversationId: string): Promise<Playbook[]> {
  const { data } = await apiClient.get<PlaybooksResponse>(
    `/conversations/${conversationId}/playbooks`,
  );
  return data.playbooks;
}

/** Path-safe encoding for `{name:path}` route segments. */
function playbookNameToUrlPath(name: string): string {
  return name
    .split("/")
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}

export async function updatePlaybookContent(
  conversationId: string,
  name: string,
  content: string,
  options?: { newName?: string },
): Promise<void> {
  const body: { content: string; name?: string } = { content };
  const next = options?.newName?.trim();
  if (next && next !== name) {
    body.name = next;
  }
  await apiClient.put(`/conversations/${conversationId}/playbooks/${playbookNameToUrlPath(name)}`, body);
}

export async function deletePlaybook(conversationId: string, name: string): Promise<void> {
  await apiClient.delete(`/conversations/${conversationId}/playbooks/${playbookNameToUrlPath(name)}`);
}
