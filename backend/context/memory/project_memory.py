"""Canonical project-scoped memory service managing a single Markdown store."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
import time
from pathlib import Path
from typing import Any

@dataclass
class ProjectMemoryEntry:
    id: str  # e.g. mem-001
    kind: str  # convention, command, architecture, lesson, strategy, heuristic, decision
    status: str  # active, stale, superseded, archived
    fact: str
    evidence: list[str] = field(default_factory=list)
    created: str = ""
    last_verified: str = ""
    confidence: float = 1.0
    source_sessions: list[str] = field(default_factory=list)
    superseded_by: list[str] = field(default_factory=list)


def parse_markdown_memory(text: str) -> list[ProjectMemoryEntry]:
    """Parse a structured Markdown project memory file into entries."""
    entries = []
    blocks = re.split(r'\n##\s+', '\n' + text)
    for block in blocks:
        block = block.strip()
        if not block or block.startswith('# '):
            continue
        lines = block.splitlines()
        header_line = lines[0].strip()
        header_parts = [p.strip() for p in header_line.split('·')]
        if len(header_parts) < 3:
            continue
        entry_id, kind, status = header_parts[0], header_parts[1], header_parts[2]
        
        fact = ""
        evidence = []
        created = ""
        last_verified = ""
        confidence = 1.0
        source_sessions = []
        superseded_by = []
        
        in_evidence = False
        for line in lines[1:]:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if line_stripped.startswith('**Fact:**'):
                fact = line_stripped[9:].strip()
                in_evidence = False
            elif line_stripped.startswith('**Evidence:**'):
                in_evidence = True
            elif line_stripped.startswith('**Created:**'):
                created = line_stripped[12:].strip()
                in_evidence = False
            elif line_stripped.startswith('**Last verified:**'):
                last_verified = line_stripped[18:].strip()
                in_evidence = False
            elif line_stripped.startswith('**Confidence:**'):
                try:
                    confidence = float(line_stripped[15:].strip())
                except ValueError:
                    confidence = 1.0
                in_evidence = False
            elif line_stripped.startswith('**Source sessions:**'):
                source_sessions = [s.strip() for s in line_stripped[20:].split(',') if s.strip()]
                in_evidence = False
            elif line_stripped.startswith('**Superseded by:**'):
                superseded_by = [s.strip() for s in line_stripped[18:].split(',') if s.strip()]
                in_evidence = False
            elif in_evidence:
                if line_stripped.startswith('---'):
                    in_evidence = False
                elif line_stripped.startswith('- ') or line_stripped.startswith('* '):
                    evidence.append(line_stripped[2:].strip())
                else:
                    evidence.append(line_stripped)
        
        entries.append(ProjectMemoryEntry(
            id=entry_id,
            kind=kind,
            status=status,
            fact=fact,
            evidence=evidence,
            created=created,
            last_verified=last_verified,
            confidence=confidence,
            source_sessions=source_sessions,
            superseded_by=superseded_by
        ))
    return entries


def serialize_markdown_memory(entries: list[ProjectMemoryEntry]) -> str:
    """Serialize project memory entries back to standard Markdown format."""
    lines = ["# Grinta Project Memory", ""]
    for entry in entries:
        lines.append(f"## {entry.id} · {entry.kind} · {entry.status}")
        lines.append("")
        lines.append(f"**Fact:** {entry.fact}")
        lines.append("")
        lines.append("**Evidence:**")
        if entry.evidence:
            for ev in entry.evidence:
                lines.append(f"- {ev}")
        else:
            lines.append("- None")
        lines.append("")
        lines.append(f"**Created:** {entry.created}")
        lines.append(f"**Last verified:** {entry.last_verified}")
        lines.append(f"**Confidence:** {entry.confidence:.2f}")
        if entry.source_sessions:
            lines.append(f"**Source sessions:** {', '.join(entry.source_sessions)}")
        if entry.superseded_by:
            lines.append(f"**Superseded by:** {', '.join(entry.superseded_by)}")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _facts_are_similar(fact1: str, fact2: str) -> bool:
    """Determine Jaccard word-overlap similarity between two facts."""
    def get_words(text: str):
        return set(re.findall(r'[a-z0-9]+', text.lower()))
    w1 = get_words(fact1)
    w2 = get_words(fact2)
    if not w1 or not w2:
        return False
    intersection = len(w1 & w2)
    union = len(w1 | w2)
    return (intersection / union) >= 0.65


class ProjectMemoryService:
    """Service to load, save, and upsert canonical project memories."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        if workspace_root is None:
            from backend.core.workspace_resolution import get_effective_workspace_root
            workspace_root = get_effective_workspace_root()
        self.workspace_root = workspace_root
        
    def _memory_file_path(self) -> Path:
        if self.workspace_root is not None:
            p = self.workspace_root / '.grinta' / 'project_memory.md'
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        from backend.core.workspace_resolution import workspace_agent_state_dir
        return workspace_agent_state_dir() / 'project_memory.md'
        
    def load(self) -> list[ProjectMemoryEntry]:
        p = self._memory_file_path()
        if not p.is_file():
            return []
        try:
            return parse_markdown_memory(p.read_text(encoding='utf-8'))
        except Exception:
            return []
            
    def save(self, entries: list[ProjectMemoryEntry]) -> None:
        p = self._memory_file_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(serialize_markdown_memory(entries), encoding='utf-8')

    def upsert_candidate(
        self,
        kind: str,
        fact: str,
        evidence: list[str] | None = None,
        confidence: float = 1.0,
        source_session: str | None = None
    ) -> str:
        """Upsert a new memory candidate, merging with existing active entries if similar."""
        entries = self.load()
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        evidence = evidence or []
        
        # Find existing active entry with similar fact
        existing = None
        for entry in entries:
            if entry.status == 'active' and _facts_are_similar(entry.fact, fact):
                existing = entry
                break
                
        if existing:
            existing.last_verified = now
            for ev in evidence:
                if ev not in existing.evidence:
                    existing.evidence.append(ev)
            if source_session and source_session not in existing.source_sessions:
                existing.source_sessions.append(source_session)
            existing.confidence = max(existing.confidence, confidence)
            self.save(entries)
            return existing.id
        else:
            max_num = 0
            for entry in entries:
                match = re.match(r'mem-(\d+)', entry.id)
                if match:
                    max_num = max(max_num, int(match.group(1)))
            next_id = f"mem-{max_num + 1:03d}"
            
            new_entry = ProjectMemoryEntry(
                id=next_id,
                kind=kind,
                status='active',
                fact=fact,
                evidence=evidence,
                created=now,
                last_verified=now,
                confidence=confidence,
                source_sessions=[source_session] if source_session else []
            )
            entries.append(new_entry)
            self.save(entries)
            return next_id

    def supersede_entry(self, entry_id: str, superseded_by_id: str) -> bool:
        entries = self.load()
        found = False
        for entry in entries:
            if entry.id == entry_id:
                entry.status = 'superseded'
                if superseded_by_id not in entry.superseded_by:
                    entry.superseded_by.append(superseded_by_id)
                found = True
                break
        if found:
            self.save(entries)
        return found

    def mark_stale(self, entry_id: str) -> bool:
        entries = self.load()
        found = False
        for entry in entries:
            if entry.id == entry_id:
                entry.status = 'stale'
                found = True
                break
        if found:
            self.save(entries)
        return found

    def archive_entry(self, entry_id: str) -> bool:
        entries = self.load()
        found = False
        for entry in entries:
            if entry.id == entry_id:
                entry.status = 'archived'
                found = True
                break
        if found:
            self.save(entries)
        return found

    def retrieve_relevant(self, query: str, limit: int = 5) -> list[ProjectMemoryEntry]:
        """Rank and return active entries based on query token Jaccard overlap."""
        entries = [e for e in self.load() if e.status == 'active']
        if not query:
            return entries[:limit]
        
        def get_words(text: str):
            return set(re.findall(r'[a-z0-9]+', text.lower()))
        
        query_words = get_words(query)
        if not query_words:
            return entries[:limit]
            
        scored = []
        for entry in entries:
            entry_words = get_words(entry.fact) | get_words(entry.kind)
            overlap = len(query_words & entry_words)
            scored.append((overlap, entry))
            
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]


def migrate_legacy_memories(workspace_root: Path | None = None) -> None:
    """Migrate legacy workspace_memory.json and lessons.md to project_memory.md."""
    from backend.engine.tools.workspace_memory import list_entries
    from backend.core.workspace_resolution import workspace_agent_state_dir
    
    service = ProjectMemoryService(workspace_root)
    pm_file = service._memory_file_path()
    if pm_file.is_file():
        return
        
    migrated_facts = []
    
    try:
        json_entries = list_entries()
        for je in json_entries:
            kind = je.get('kind', 'lesson')
            key = je.get('key', '')
            value = je.get('value', '')
            if key == 'session_summary' or kind == 'preference':
                continue
            fact = f"{key}: {value}" if key else value
            migrated_facts.append((kind, fact, je.get('created', ''), je.get('seen_count', 1)))
    except Exception:
        pass
        
    if workspace_root is None:
        from backend.core.workspace_resolution import get_effective_workspace_root
        workspace_root = get_effective_workspace_root()
        
    if workspace_root:
        paths = [
            workspace_agent_state_dir(workspace_root) / 'lessons.md',
            workspace_root / 'memories' / 'repo' / 'lessons.md'
        ]
        for path in paths:
            if path.is_file():
                try:
                    content = path.read_text(encoding='utf-8')
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith('- ') or line.startswith('* '):
                            fact = line[2:].strip()
                            if fact and not any(f[1] == fact for f in migrated_facts):
                                migrated_facts.append(('lesson', fact, '', 1))
                        elif line and not line.startswith('#') and not line.startswith('---'):
                            if not any(f[1] == line for f in migrated_facts):
                                migrated_facts.append(('lesson', line, '', 1))
                except Exception:
                    pass
                    
    for kind, fact, created, seen_count in migrated_facts:
        service.upsert_candidate(
            kind=kind,
            fact=fact,
            confidence=0.9,
            evidence=[f"Migrated from legacy store (seen {seen_count} times)."]
        )
