import apiClient from "./client";
import type {
  KBCollection,
  KBDocument,
  KBSearchResult,
  CreateCollectionPayload,
  SearchPayload,
  KBStats,
} from "@/types/knowledge";

const BASE = "/v1/knowledge-base";

export async function listCollections(): Promise<KBCollection[]> {
  const res = await apiClient.get<KBCollection[]>(`${BASE}/collections`);
  return res.data;
}

export async function createCollection(
  payload: CreateCollectionPayload,
): Promise<KBCollection> {
  const res = await apiClient.post<KBCollection>(
    `${BASE}/collections`,
    payload,
  );
  return res.data;
}

export async function deleteCollection(id: string): Promise<void> {
  await apiClient.delete(`${BASE}/collections/${id}`);
}

export async function listDocuments(collectionId: string): Promise<KBDocument[]> {
  const res = await apiClient.get<KBDocument[]>(
    `${BASE}/collections/${collectionId}/documents`,
  );
  return res.data;
}

export async function uploadDocument(
  collectionId: string,
  file: File,
): Promise<KBDocument> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiClient.post<KBDocument>(
    `${BASE}/collections/${collectionId}/documents`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}

export async function uploadTextDocument(
  collectionId: string,
  filename: string,
  content: string,
): Promise<KBDocument> {
  const blob = new Blob([content], { type: "text/plain" });
  const file = new File([blob], filename, { type: "text/plain" });
  return uploadDocument(collectionId, file);
}

export async function deleteDocument(documentId: string): Promise<void> {
  await apiClient.delete(`${BASE}/documents/${documentId}`);
}

export async function searchKB(
  payload: SearchPayload,
): Promise<KBSearchResult[]> {
  const res = await apiClient.post<KBSearchResult[]>(`${BASE}/search`, payload);
  return res.data;
}

export async function getStats(): Promise<KBStats> {
  const res = await apiClient.get<KBStats>(`${BASE}/stats`);
  return res.data;
}
