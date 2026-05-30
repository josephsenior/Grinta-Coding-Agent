# 39. The Semantic Memory That Survived

There is a specific kind of embarrassment in engineering: the gap between what you built and what you actually needed.

Earlier versions of Grinta had a memory subsystem that was genuinely impressive. A graph-based knowledge store with typed nodes for files, classes, functions, and concepts, connected by edges for imports, calls, definitions, and inheritance. A vector store that combined ANN search with BM25 lexical retrieval and cross-encoder re-ranking using full PyTorch models. A hierarchical context manager with three tiers — short-term, working, and long-term — plus explicit decision tracking and context anchors that should never be dropped.

It was over 15,000 lines of infrastructure. It was also too heavy to ship.

This chapter is about what survived that deletion, why it survived, and how the current RAG stack ended up being both simpler and more honest than the original.

---

## What Got Killed

Three things had to die, and each one died for a different reason.

### The Graph Memory Store

The graph memory built a typed knowledge graph using NetworkX. Nodes represented files, classes, functions, variables, and concepts. Edges represented imports, calls, definitions, inheritance, and references. The retrieval module combined that graph with a hybrid vector-plus-BM25 search to answer questions like *"How does the authentication middleware relate to the billing module?"*

It worked. It was also a NetworkX dependency plus a full knowledge graph index plus a retrieval pipeline that took noticeable seconds to warm up on a medium-sized codebase. For a CLI agent whose north star is instant boot and zero-config startup, that was architectural theater. I kept it strictly optional and eventually stripped it entirely because carrying a graph database just to index code felt like building a library to read a pamphlet.

### The Cross-Encoder Reranker

The original vector store used sentence-transformers with a cross-encoder model for re-ranking hybrid search results. The pipeline was: retrieve 20 candidates from the vector backend, retrieve 20 from BM25, deduplicate, then re-rank all 40 through the cross-encoder and return the top 5.

The cross-encoder was accurate. It was also a PyTorch dependency that added hundreds of megabytes to the install footprint. For a project that ships as a ~1.4 MB wheel, that was unacceptable. The cross-encoder was killed and replaced with an optional flashrank reranker using TinyBERT — ONNX-based, fast, and only loaded when the `[rag]` extra is installed.

### The Semantic Condenser

The context compaction system had a `SemanticCondenser` that scored events by semantic importance using cosine similarity embeddings. The idea was elegant: instead of heuristically scoring events by type and recency, actually measure how semantically important each event was to the current task.

It did not work reliably enough to justify the embedding dependency. The heuristic-based `SmartCompactor` scored events by type (user messages > agent actions > observations > status updates), recency, and whether they were anchored by the task tracker. It was not as sophisticated as semantic scoring, but it was deterministic, fast, and did not require loading an embedding model just to decide what to keep in context.

---

## What Survived

What remained after the deletions was not the ambitious system I originally designed. It was something smaller, leaner, and more honest about its constraints.

### The Dual-Backend Architecture

The current vector store (`backend/context/vector_store.py`) has two backends that run in parallel:

**ChromaDB with FastEmbed ONNX** — The semantic backend uses ChromaDB's persistent client with FastEmbed's `BAAI/bge-small-en-v1.5` model. This is an ONNX-based embedding function, not PyTorch. It produces 384-dimensional vectors, loads in the background without blocking startup, and persists to `~/.grinta/workspaces/<id>/storage/memory/chroma/`. The model is configurable via the `EMBEDDING_MODEL` environment variable.

**SQLite FTS5 with BM25** — The lexical backend is a SQLite virtual table using the FTS5 extension with BM25 ranking. No external dependencies beyond Python's built-in `sqlite3`. It persists to `~/.grinta/workspaces/<id>/storage/memory/sqlite/` and handles keyword-exact queries that semantic search sometimes misses — function names, error codes, specific identifiers.

Both backends implement the same `VectorBackend` abstract interface. The `EnhancedVectorStore` orchestrates them: add goes to both, search runs both in parallel via `ThreadPoolExecutor`, results are deduplicated by `step_id`, and the top-k winners are returned.

### Parent-Child Chunking

The ChromaDB backend does not store documents as single blobs. It uses a parent-child strategy:

1. The **parent document** is the full context (rationale + content, capped at 2,000 characters), stored with `is_child: False`.
2. If the text exceeds 600 characters, it is split into **child chunks** of 400 characters with 100-character overlap, each tagged with `is_child: True` and a `parent_id` reference.

At search time, the query targets child chunks specifically — because a 400-character chunk is more likely to produce a precise semantic match than a 2,000-character blob. But the results are mapped back to their parent documents, so the agent receives the full context, not just the matching fragment.

This is the kind of detail that separates a retrieval system that works from one that feels like it works. A child match without parent context is a quote without a source. The parent-child pattern ensures the agent gets both.

### The LRU Query Cache

Every search goes through an LRU cache (`QueryCache`) with a configurable size (default 10,000 entries) and TTL (default 1 hour). The cache key is a SHA-256 hash of the query, and results are stored with timestamps. On hit, the cache returns in sub-millisecond time. On miss, both backends run, results are merged and re-ranked, then cached for the next query.

The cache also supports selective invalidation: when documents are deleted by metadata or step ID, the corresponding cache entries are evicted so stale results do not leak through.

### Optional FlashRank Re-Ranking

If the `[rag]` extra includes `flashrank`, the store loads a `ms-marco-TinyBERT-L-2-v2` reranker — ONNX-based, lightweight, and fast. The reranker takes the deduplicated candidates from both backends and re-scores them against the query, returning a more accurate top-k.

If flashrank is not installed, the store falls back to the raw candidate order. The reranker is explicitly optional — the system works without it, but works better with it.

### Async-First Design

Every operation has an async wrapper: `async_add`, `async_add_batch`, `async_search`. These use `asyncio.to_thread` to offload CPU and I/O-heavy operations to worker threads, keeping the event loop responsive during embedding computation and disk writes. The model warmup itself runs in a daemon thread so that `__init__` returns instantly and the agent can start working while the embedding model loads in the background.

---

## The Integration Story

The vector store is not a standalone feature. It is wired into the conversation memory layer (`backend/context/conversation_memory.py`) and serves three purposes:

### 1. Semantic Event Indexing

When the agent processes an event (a tool call, an observation, a message), the conversation memory indexes it into the vector store with metadata: `step_id`, `role` (user/assistant/tool), `artifact_hash`, and `timestamp`. The indexed content is the event's text — the tool's output, the agent's reasoning, the user's question.

This means the agent's entire session history is searchable by semantic similarity, not just by recency. When the context window fills and compaction kicks in, the system can recall semantically relevant events from earlier in the session that would otherwise be lost.

### 2. Recall Observations

The agent can explicitly query its own memory through `RecallObservation` events. When the agent asks a question about something it discussed earlier in the session, the conversation memory searches the vector store, retrieves the top-k relevant events, and injects them back into the context as a recall observation. This is not a separate tool call — it is part of the event processing pipeline, triggered when the agent's behavior indicates it has lost context.

### 3. Condensation Anchoring

The compaction system reads the task tracker (`active_plan.json`) to identify which steps are still in progress. Those steps are marked as essential events that survive compaction. The vector store reinforces this by providing semantic recall for events that are semantically related to the active task, even if they are not directly anchored by the tracker.

---

## Why This Architecture

Each decision in the current stack was earned through deletion, not addition.

**ONNX over PyTorch** — The install footprint matters. A coding agent that requires PyTorch to remember things is an agent that has forgotten its own constraints. FastEmbed's ONNX models are small, fast, and do not pull in the PyTorch dependency tree.

**SQLite over another vector database** — Python ships with SQLite. FTS5 ships with SQLite. BM25 ships with FTS5. There is no installation step, no daemon to manage, no network port to configure. The lexical backend is zero-dependency by design.

**Parallel backends over a single backend** — Semantic search misses exact matches. Lexical search misses conceptual matches. Running both in parallel and deduplicating by step_id gives the agent the best of both worlds without requiring the user to choose.

**Parent-child chunking over flat documents** — A 2,000-character blob dilutes semantic signals. A 400-character chunk concentrates them. But the agent needs the full context, not just the matching fragment. The parent-child pattern solves both problems.

**Optional reranking over mandatory reranking** — The system works without flashrank. It works better with it. Making it optional means the base install stays lean, and users who want maximum retrieval accuracy can opt in.

**Background warmup over blocking startup** — The embedding model takes a few seconds to load. The agent should not wait for it. The model loads in a daemon thread, and the first search that needs it blocks only if the model is not ready yet. In practice, the model is usually warm by the time the agent needs it.

---

## The Honest Assessment

The current RAG stack is not the ambitious system I originally designed. It does not have a knowledge graph. It does not have cross-encoder re-ranking with full PyTorch models. It does not have a three-tier hierarchical memory manager with decision tracking.

What it does have is:

- A dual-backend architecture that runs semantic and lexical search in parallel
- Parent-child chunking for precise retrieval with full context
- An LRU query cache with selective invalidation
- Optional flashrank re-ranking for higher accuracy
- Async-first design that keeps the event loop responsive
- Background model warmup that does not block startup
- Zero mandatory dependencies beyond ChromaDB and SQLite

That is not the system I wanted to build. It is the system the project could actually ship. And in engineering, that distinction is the one that matters.

The GraphRAG conundrum from [18 · The Mind of the Agent](18-the-mind-of-the-agent.md) was real: beautiful, over-engineered magic that cost too much to run. What survived is less magical but more honest. It does the job, it stays out of the way, and it does not pretend to be something it is not.

That is the RAG stack that earned its place in Grinta.

---

← [The Vendor-Neutral Bench](38-the-vendor-neutral-bench.md) | [The Book of Grinta](README.md) | [The Facade Pattern and the Smaller File API](40-the-facade-pattern-and-the-smaller-file-api.md) →
