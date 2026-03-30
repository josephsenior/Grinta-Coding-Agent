"""Agent-facing error recovery via Knowledge Base search (record / query / list).

One-time migration can import legacy ``query_error_solutions`` JSON into the KB.
Orchestrator no longer injects regex- or substring-based recovery hints into prompts;
this tool is the supported path to persist and retrieve recovery notes.
"""

from __future__ import annotations

import getpass
import hashlib
import json
from pathlib import Path
from typing import Any

from backend.ledger.action.agent import AgentThinkAction
from backend.knowledge.knowledge_base_manager import KnowledgeBaseManager

ERROR_RECOVERY_MEMORY_TOOL_NAME = "error_recovery_memory"

_COLLECTION_NAME = "Error Recovery Memory"
_MIGRATION_MARKER = ".app/error_recovery_migration_done.json"
_LEGACY_LOCAL_FILE = ".app/query_error_solutions.json"
_LEGACY_GLOBAL_FILE = Path.home() / ".app" / "global_query_error_solutions.json"


def _workspace_root() -> Path:
    from backend.core.workspace_resolution import require_effective_workspace_root

    return require_effective_workspace_root()


def _migration_marker_path() -> Path:
    return _workspace_root() / _MIGRATION_MARKER


def _legacy_local_path() -> Path:
    return _workspace_root() / _LEGACY_LOCAL_FILE


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except (OSError, json.JSONDecodeError):
        return []
    return []


def _kb_manager() -> KnowledgeBaseManager:
    # Keep a stable per-user namespace without coupling this tool to request context.
    return KnowledgeBaseManager(user_id=getpass.getuser() or "default")


def _ensure_collection(manager: KnowledgeBaseManager) -> str:
    for collection in manager.list_collections():
        if collection.name == _COLLECTION_NAME:
            return collection.id
    created = manager.create_collection(
        name=_COLLECTION_NAME,
        description="Recovered fixes and troubleshooting notes for recurring errors.",
    )
    return created.id


def _build_doc_content(error_signature: str, solution: str, source: str) -> str:
    payload = {
        "error_signature": error_signature,
        "solution": solution,
        "source": source,
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_doc_name(error_signature: str, solution: str) -> str:
    raw = f"{error_signature}\n{solution}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return f"error-recovery-{digest}.json"


def _record(manager: KnowledgeBaseManager, collection_id: str, error_signature: str, solution: str, source: str) -> bool:
    doc_content = _build_doc_content(error_signature=error_signature, solution=solution, source=source)
    doc_name = _build_doc_name(error_signature=error_signature, solution=solution)
    doc = manager.add_document(
        collection_id=collection_id,
        filename=doc_name,
        content=doc_content,
        mime_type="application/json",
        metadata={"error_signature": error_signature, "source": source},
    )
    return doc is not None


def _run_one_time_migration(manager: KnowledgeBaseManager, collection_id: str) -> tuple[int, int]:
    marker = _migration_marker_path()
    if marker.exists():
        return (0, 0)

    local_patterns = _load_json_list(_legacy_local_path())
    global_patterns = _load_json_list(_LEGACY_GLOBAL_FILE)

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in local_patterns + global_patterns:
        trigger = str(entry.get("trigger", "") or "").strip()
        if not trigger or trigger in seen:
            continue
        merged.append(entry)
        seen.add(trigger)

    imported = 0
    skipped = 0
    for entry in merged:
        trigger = str(entry.get("trigger", "") or "").strip()
        solution = str(entry.get("solution", "") or "").strip()
        if not trigger or not solution:
            skipped += 1
            continue
        ok = _record(
            manager,
            collection_id,
            error_signature=trigger,
            solution=solution,
            source="legacy_query_error_solutions",
        )
        if ok:
            imported += 1
        else:
            skipped += 1

    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {"migrated": True, "imported": imported, "skipped": skipped},
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        # Non-fatal: migration remains logically complete for this run.
        pass
    return (imported, skipped)


def create_error_recovery_memory_tool() -> dict:
    return {
        "type": "function",
        "function": {
            "name": ERROR_RECOVERY_MEMORY_TOOL_NAME,
            "description": (
                "Primary recovery aid: store and query verified fixes via Knowledge Base search. "
                "Use 'record' after you confirm a fix, 'query' with an error signature to find similar "
                "past fixes, 'list' to browse entries, 'migrate_legacy' once to import legacy JSON patterns."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "enum": ["record", "query", "list", "migrate_legacy"],
                        "description": "Operation to perform.",
                    },
                    "error_signature": {
                        "type": "string",
                        "description": "Error text/signature to record or query.",
                    },
                    "solution": {
                        "type": "string",
                        "description": "Verified recovery guidance for record command.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of query results to return (default 5).",
                    },
                },
                "required": ["command"],
            },
        },
    }


def build_error_recovery_memory_action(arguments: dict[str, Any]) -> AgentThinkAction:
    command = str(arguments.get("command", "list") or "list")
    manager = _kb_manager()
    collection_id = _ensure_collection(manager)

    # Ensure existing users don't lose prior learned fixes.
    _run_one_time_migration(manager, collection_id)

    if command == "migrate_legacy":
        imported, skipped = _run_one_time_migration(manager, collection_id)
        return AgentThinkAction(
            thought=(
                "[ERROR_RECOVERY_MEMORY] Legacy migration complete. "
                f"Imported={imported}, Skipped={skipped}."
            )
        )

    if command == "record":
        error_signature = str(arguments.get("error_signature", "") or "").strip()
        solution = str(arguments.get("solution", "") or "").strip()
        if not error_signature or not solution:
            return AgentThinkAction(
                thought="[ERROR_RECOVERY_MEMORY] record requires both 'error_signature' and 'solution'."
            )
        ok = _record(
            manager,
            collection_id,
            error_signature=error_signature,
            solution=solution,
            source="manual_record",
        )
        if ok:
            return AgentThinkAction(
                thought=f"[ERROR_RECOVERY_MEMORY] Recorded recovery: {error_signature}"
            )
        return AgentThinkAction(
            thought="[ERROR_RECOVERY_MEMORY] Failed to record recovery entry."
        )

    if command == "query":
        error_signature = str(arguments.get("error_signature", "") or "").strip()
        if not error_signature:
            return AgentThinkAction(
                thought="[ERROR_RECOVERY_MEMORY] query requires 'error_signature'."
            )
        top_k = int(arguments.get("top_k", 5) or 5)
        results = manager.search(
            query=error_signature,
            collection_ids=[collection_id],
            top_k=max(1, min(top_k, 10)),
            relevance_threshold=0.7,
        )
        if not results:
            return AgentThinkAction(
                thought="[ERROR_RECOVERY_MEMORY] No relevant recovery entries found."
            )
        lines = ["[ERROR_RECOVERY_MEMORY] Ranked recoveries:"]
        for idx, result in enumerate(results, start=1):
            lines.append(
                f"  {idx}. ({result.relevance_score:.3f}) {result.chunk_content[:300]}"
            )
        return AgentThinkAction(thought="\n".join(lines))

    if command == "list":
        docs = manager.list_documents(collection_id)
        if not docs:
            return AgentThinkAction(
                thought="[ERROR_RECOVERY_MEMORY] No recovery entries recorded yet."
            )
        preview = [
            f"  {idx}. {doc.filename} ({doc.chunk_count} chunks)"
            for idx, doc in enumerate(docs[:25], start=1)
        ]
        return AgentThinkAction(
            thought="[ERROR_RECOVERY_MEMORY] Stored entries:\n" + "\n".join(preview)
        )

    return AgentThinkAction(
        thought=(
            "[ERROR_RECOVERY_MEMORY] Unknown command. "
            "Use one of: record | query | list | migrate_legacy"
        )
    )
