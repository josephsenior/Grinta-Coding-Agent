import apiClient from "./client";

export interface Playbook {
  name: string;
  description?: string;
  type?: string;
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
