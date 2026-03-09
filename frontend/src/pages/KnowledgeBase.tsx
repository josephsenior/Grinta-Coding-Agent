import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Plus,
  Trash2,
  Upload,
  Search,
  ChevronRight,
  ChevronDown,
  FileText,
  X,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  listCollections,
  createCollection,
  deleteCollection,
  listDocuments,
  uploadDocument,
  uploadTextDocument,
  deleteDocument,
  searchKB,
} from "@/api/knowledge";
import type { KBCollection, KBDocument, KBSearchResult } from "@/types/knowledge";

// ─── Confirm Dialog ───────────────────────────────────────────────────────────

function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  title: string;
  description: string;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">{description}</p>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              onConfirm();
              onOpenChange(false);
            }}
          >
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Collection Row ───────────────────────────────────────────────────────────

function CollectionRow({
  collection,
  onDelete,
}: {
  collection: KBCollection;
  onDelete: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [deleteDocTarget, setDeleteDocTarget] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const { data: documents = [], isLoading: docsLoading } = useQuery({
    queryKey: ["kb-docs", collection.id],
    queryFn: () => listDocuments(collection.id),
    enabled: expanded,
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(collection.id, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-docs", collection.id] });
      qc.invalidateQueries({ queryKey: ["kb-collections"] });
      toast.success("Document uploaded");
    },
    onError: () => toast.error("Upload failed"),
  });

  const deleteDocMutation = useMutation({
    mutationFn: (docId: string) => deleteDocument(docId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-docs", collection.id] });
      qc.invalidateQueries({ queryKey: ["kb-collections"] });
      toast.success("Document deleted");
    },
    onError: () => toast.error("Failed to delete document"),
  });

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      uploadMutation.mutate(file);
      e.target.value = "";
    }
  }

  return (
    <div className="rounded-lg border bg-card">
      {/* Collection header */}
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          className="flex items-center gap-2 flex-1 text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="font-medium">{collection.name}</span>
          {collection.description && (
            <span className="text-sm text-muted-foreground truncate max-w-xs">
              — {collection.description}
            </span>
          )}
        </button>

        <div className="flex items-center gap-2 shrink-0">
          <Badge variant="secondary" className="text-xs">
            {collection.document_count}{" "}
            {collection.document_count === 1 ? "doc" : "docs"}
          </Badge>
          <Badge variant="outline" className="text-xs">
            {collection.total_size_mb} MB
          </Badge>

          <input
            type="file"
            ref={fileInputRef}
            className="hidden"
            accept="text/*,.md,.txt,.py,.ts,.js,.json,.yaml,.toml,.csv"
            onChange={handleFileChange}
          />
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
          >
            {uploadMutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Upload className="h-3.5 w-3.5" />
            )}
            <span className="ml-1">Upload</span>
          </Button>

          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 text-xs"
            onClick={() => setUploadOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="ml-1">Paste</span>
          </Button>

          <Button
            size="sm"
            variant="ghost"
            className="h-7 w-7 p-0 text-destructive hover:text-destructive"
            onClick={() => onDelete(collection.id)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Documents list */}
      {expanded && (
        <div className="border-t px-4 py-2">
          {docsLoading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading documents…
            </div>
          ) : documents.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">
              Datastore empty. Index local files or inject raw blocks to commence.
            </p>
          ) : (
            <ul className="divide-y">
              {documents.map((doc) => (
                <DocumentRow
                  key={doc.id}
                  doc={doc}
                  onDelete={() => setDeleteDocTarget(doc.id)}
                />
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Paste text dialog */}
      <PasteTextDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        collectionId={collection.id}
        onUploaded={() => {
          qc.invalidateQueries({ queryKey: ["kb-docs", collection.id] });
          qc.invalidateQueries({ queryKey: ["kb-collections"] });
        }}
      />

      {/* Delete document confirm */}
      <ConfirmDialog
        open={!!deleteDocTarget}
        onOpenChange={(v) => !v && setDeleteDocTarget(null)}
        title="Delete document?"
        description="This will permanently remove the document and all its chunks."
        onConfirm={() => {
          if (deleteDocTarget) {
            deleteDocMutation.mutate(deleteDocTarget);
            setDeleteDocTarget(null);
          }
        }}
      />
    </div>
  );
}

// ─── Document Row ─────────────────────────────────────────────────────────────

function DocumentRow({
  doc,
  onDelete,
}: {
  doc: KBDocument;
  onDelete: () => void;
}) {
  return (
    <li className="flex items-center gap-3 py-2">
      <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
      <div className="flex-1 min-w-0">
        <span className="truncate text-sm font-medium">{doc.filename}</span>
        {doc.content_preview && (
          <p className="truncate text-xs text-muted-foreground mt-0.5">
            {doc.content_preview}
          </p>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0 text-xs text-muted-foreground">
        <span>{doc.file_size_kb} KB</span>
        <span>·</span>
        <span>{doc.chunk_count} chunks</span>
      </div>
      <Button
        size="sm"
        variant="ghost"
        className="h-6 w-6 p-0 text-muted-foreground hover:text-destructive"
        onClick={onDelete}
      >
        <X className="h-3 w-3" />
      </Button>
    </li>
  );
}

// ─── Paste Text Dialog ────────────────────────────────────────────────────────

function PasteTextDialog({
  open,
  onOpenChange,
  collectionId,
  onUploaded,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  collectionId: string;
  onUploaded: () => void;
}) {
  const [filename, setFilename] = useState("");
  const [content, setContent] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      uploadTextDocument(collectionId, filename || "pasted-text.txt", content),
    onSuccess: () => {
      toast.success("Text document added");
      onUploaded();
      onOpenChange(false);
      setFilename("");
      setContent("");
    },
    onError: () => toast.error("Failed to add text document"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Paste Text</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Input
            placeholder="Filename (e.g. notes.md)"
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
          />
          <Textarea
            placeholder="Paste your text content here…"
            className="min-h-[200px] font-mono text-sm"
            value={content}
            onChange={(e) => setContent(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={!content.trim() || mutation.isPending}
          >
            {mutation.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            Add Document
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Search Panel ─────────────────────────────────────────────────────────────

function SearchPanel({ collections }: { collections: KBCollection[] }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<KBSearchResult[]>([]);
  const [searched, setSearched] = useState(false);

  const searchMutation = useMutation({
    mutationFn: () =>
      searchKB({ query, top_k: 5, relevance_threshold: 0.3 }),
    onSuccess: (data) => {
      setResults(data);
      setSearched(true);
    },
    onError: () => toast.error("Search failed"),
  });

  const collectionName = (id: string) =>
    collections.find((c) => c.id === id)?.name ?? id;

  return (
    <div className="rounded-lg border bg-card p-4">
      <h2 className="mb-3 text-sm font-semibold">Search</h2>
      <div className="flex gap-2">
        <Input
          placeholder="Search across all collections…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && query.trim()) searchMutation.mutate();
          }}
        />
        <Button
          onClick={() => searchMutation.mutate()}
          disabled={!query.trim() || searchMutation.isPending}
          size="sm"
        >
          {searchMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Search className="h-4 w-4" />
          )}
        </Button>
      </div>

      {searched && (
        <div className="mt-3 space-y-2">
          {results.length === 0 ? (
            <p className="text-sm text-muted-foreground">No results found.</p>
          ) : (
            results.map((r, i) => (
              <div key={i} className="rounded-md border p-3 text-sm">
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="font-medium truncate">{r.filename}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline" className="text-xs">
                      {collectionName(r.collection_id)}
                    </Badge>
                    <Badge
                      variant="secondary"
                      className="text-xs tabular-nums"
                    >
                      {(r.relevance_score * 100).toFixed(0)}%
                    </Badge>
                  </div>
                </div>
                <p className="text-muted-foreground text-xs leading-relaxed line-clamp-3">
                  {r.chunk_content}
                </p>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ─── Create Collection Dialog ─────────────────────────────────────────────────

function CreateCollectionDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const qc = useQueryClient();

  const mutation = useMutation({
    mutationFn: () =>
      createCollection({ name: name.trim(), description: description.trim() || undefined }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-collections"] });
      toast.success("Collection created");
      onOpenChange(false);
      setName("");
      setDescription("");
    },
    onError: () => toast.error("Failed to create collection"),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>New Collection</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Input
            placeholder="Collection name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) mutation.mutate();
            }}
          />
          <Input
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={!name.trim() || mutation.isPending}
          >
            {mutation.isPending && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function KnowledgeBase() {
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const qc = useQueryClient();

  const { data: collections = [], isLoading } = useQuery({
    queryKey: ["kb-collections"],
    queryFn: listCollections,
  });

  const deleteColMutation = useMutation({
    mutationFn: (id: string) => deleteCollection(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-collections"] });
      toast.success("Collection deleted");
    },
    onError: () => toast.error("Failed to delete collection"),
  });

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col px-6 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BookOpen className="h-6 w-6" />
          <h1 className="text-2xl font-bold">Knowledge Base</h1>
        </div>
        <Button size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="mr-1.5 h-4 w-4" />
          New Collection
        </Button>
      </div>

      {/* Collections */}
      <div className="space-y-3 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center gap-2 py-12 justify-center text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            Loading collections…
          </div>
        ) : collections.length === 0 ? (
          <div className="py-16 text-center text-muted-foreground">
            <BookOpen className="mx-auto mb-4 h-10 w-10 opacity-30" />
            <p className="text-sm">Vault empty.</p>
            <p className="text-xs mt-1">
              Create a collection, then upload documents for the agent to
              search.
            </p>
          </div>
        ) : (
          collections.map((c) => (
            <CollectionRow
              key={c.id}
              collection={c}
              onDelete={(id) => setDeleteTarget(id)}
            />
          ))
        )}
      </div>

      {/* Search (only if collections exist) */}
      {collections.length > 0 && (
        <>
          <Separator className="my-6" />
          <SearchPanel collections={collections} />
        </>
      )}

      {/* Create collection dialog */}
      <CreateCollectionDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
      />

      {/* Delete collection confirm */}
      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(v) => !v && setDeleteTarget(null)}
        title="Delete collection?"
        description="This will permanently delete the collection and all its documents. This action cannot be undone."
        onConfirm={() => {
          if (deleteTarget) {
            deleteColMutation.mutate(deleteTarget);
            setDeleteTarget(null);
          }
        }}
      />
    </div>
  );
}

