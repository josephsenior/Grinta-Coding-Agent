import apiClient from "./client";
import type {
  ConversationListResponse,
  ConversationInfo,
  CreateConversationRequest,
} from "@/types/conversation";

export async function getConversations(
  pageId?: string,
  limit = 20,
): Promise<ConversationListResponse> {
  const params: Record<string, string | number> = { limit };
  if (pageId) params.page_id = pageId;
  const { data } = await apiClient.get<ConversationListResponse>("/conversations", {
    params,
  });
  return data;
}

export async function getConversation(id: string): Promise<ConversationInfo> {
  const { data } = await apiClient.get<ConversationInfo>(`/conversations/${id}`);
  return data;
}

export async function createConversation(
  req: CreateConversationRequest,
): Promise<ConversationInfo> {
  const { data } = await apiClient.post<ConversationInfo>("/conversations", req);
  return data;
}

export async function deleteConversation(id: string): Promise<void> {
  await apiClient.delete(`/conversations/${id}`);
}

export async function updateConversationTitle(
  id: string,
  title: string,
): Promise<void> {
  await apiClient.patch(`/conversations/${id}`, { title });
}
