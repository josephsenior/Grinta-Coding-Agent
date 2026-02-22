export interface KBCollection {
  id: string;
  name: string;
  description: string | null;
  document_count: number;
  total_size_bytes: number;
  total_size_mb: number;
  created_at: string;
  updated_at: string;
}

export interface KBDocument {
  id: string;
  collection_id: string;
  filename: string;
  file_size_bytes: number;
  file_size_kb: number;
  mime_type: string;
  content_preview: string | null;
  chunk_count: number;
  uploaded_at: string;
}

export interface KBSearchResult {
  document_id: string;
  collection_id: string;
  filename: string;
  chunk_content: string;
  relevance_score: number;
}

export interface CreateCollectionPayload {
  name: string;
  description?: string;
}

export interface SearchPayload {
  query: string;
  collection_ids?: string[] | null;
  top_k?: number;
  relevance_threshold?: number;
}

export interface KBStats {
  total_collections: number;
  total_documents: number;
  total_size_bytes: number;
  [key: string]: unknown;
}
