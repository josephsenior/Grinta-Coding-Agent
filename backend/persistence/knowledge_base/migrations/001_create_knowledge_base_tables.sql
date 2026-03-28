-- Knowledge Base Database Schema
-- Description: Tables for storing knowledge base collections and documents

-- Collections table
CREATE TABLE IF NOT EXISTS knowledge_base_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    document_count INTEGER DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Documents table
CREATE TABLE IF NOT EXISTS knowledge_base_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID NOT NULL REFERENCES knowledge_base_collections(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    mime_type TEXT NOT NULL,
    content_preview TEXT,
    chunk_count INTEGER DEFAULT 0,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_kb_collections_user_id ON knowledge_base_collections(user_id);
CREATE INDEX IF NOT EXISTS idx_kb_collections_created_at ON knowledge_base_collections(created_at);
CREATE INDEX IF NOT EXISTS idx_kb_documents_collection_id ON knowledge_base_documents(collection_id);
CREATE INDEX IF NOT EXISTS idx_kb_documents_content_hash ON knowledge_base_documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_kb_documents_uploaded_at ON knowledge_base_documents(uploaded_at);

-- Unique constraint to prevent duplicate documents in the same collection
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_documents_content_hash_collection_id
    ON knowledge_base_documents(content_hash, collection_id);
