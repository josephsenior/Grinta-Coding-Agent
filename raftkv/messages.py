"""Raft RPC message types and data structures.

All inter-node communication uses these message dataclasses.
They are serialisable via dataclasses.asdict for WAL / network transport.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeRole(enum.Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


class MessageType(enum.Enum):
    REQUEST_VOTE = "RequestVote"
    REQUEST_VOTE_RESPONSE = "RequestVoteResponse"
    APPEND_ENTRIES = "AppendEntries"
    APPEND_ENTRIES_RESPONSE = "AppendEntriesResponse"
    CLIENT_COMMAND = "ClientCommand"
    CLIENT_RESPONSE = "ClientResponse"


class ClientOp(enum.Enum):
    SET = "set"
    DELETE = "delete"
    GET = "get"


# ---------------------------------------------------------------------------
# Log entry
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    """A single entry in the Raft replicated log."""
    term: int
    index: int
    command: dict[str, Any]  # {"op": "set", "key": "x", "value": "1"} etc.

    def to_dict(self) -> dict:
        return {"term": self.term, "index": self.index, "command": self.command}

    @classmethod
    def from_dict(cls, d: dict) -> LogEntry:
        return cls(term=d["term"], index=d["index"], command=d["command"])


# ---------------------------------------------------------------------------
# RPC messages
# ---------------------------------------------------------------------------

@dataclass
class RequestVote:
    """Candidate -> Follower: request a vote."""
    type: MessageType = field(default=MessageType.REQUEST_VOTE, init=False)
    term: int = 0
    candidate_id: str = ""
    last_log_index: int = 0
    last_log_term: int = 0


@dataclass
class RequestVoteResponse:
    """Follower -> Candidate: vote grant or denial."""
    type: MessageType = field(default=MessageType.REQUEST_VOTE_RESPONSE, init=False)
    term: int = 0
    vote_granted: bool = False


@dataclass
class AppendEntries:
    """Leader -> Follower: heartbeat or log replication."""
    type: MessageType = field(default=MessageType.APPEND_ENTRIES, init=False)
    term: int = 0
    leader_id: str = ""
    prev_log_index: int = 0
    prev_log_term: int = 0
    entries: list[LogEntry] = field(default_factory=list)
    leader_commit: int = 0


@dataclass
class AppendEntriesResponse:
    """Follower -> Leader: success or failure of AppendEntries."""
    type: MessageType = field(default=MessageType.APPEND_ENTRIES_RESPONSE, init=False)
    term: int = 0
    success: bool = False
    match_index: int = 0  # highest log index known to be replicated


@dataclass
class ClientCommand:
    """Client -> Node: a write or read command."""
    type: MessageType = field(default=MessageType.CLIENT_COMMAND, init=False)
    op: ClientOp = ClientOp.GET
    key: str = ""
    value: Any = None
    request_id: str = ""  # for idempotency / correlation


@dataclass
class ClientResponse:
    """Node -> Client: result of a command."""
    type: MessageType = field(default=MessageType.CLIENT_RESPONSE, init=False)
    success: bool = False
    value: Any = None
    leader_id: str | None = None  # hint for client redirect
    error: str = ""
    request_id: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def msg_to_dict(msg: Any) -> dict:
    """Convert any message dataclass to a plain dict (recursively for LogEntries)."""
    d = asdict(msg)
    # Ensure MessageType enum serialises cleanly
    if "type" in d and isinstance(d["type"], MessageType):
        d["type"] = d["type"].value
    return d


def msg_from_dict(d: dict) -> Any:
    """Reconstruct a message dataclass from a plain dict."""
    msg_type = d.get("type")
    if msg_type in (MessageType.REQUEST_VOTE.value, "RequestVote"):
        return RequestVote(
            term=d["term"],
            candidate_id=d["candidate_id"],
            last_log_index=d["last_log_index"],
            last_log_term=d["last_log_term"],
        )
    if msg_type in (MessageType.REQUEST_VOTE_RESPONSE.value, "RequestVoteResponse"):
        return RequestVoteResponse(term=d["term"], vote_granted=d["vote_granted"])
    if msg_type in (MessageType.APPEND_ENTRIES.value, "AppendEntries"):
        entries = [LogEntry.from_dict(e) for e in d.get("entries", [])]
        return AppendEntries(
            term=d["term"],
            leader_id=d["leader_id"],
            prev_log_index=d["prev_log_index"],
            prev_log_term=d["prev_log_term"],
            entries=entries,
            leader_commit=d["leader_commit"],
        )
    if msg_type in (MessageType.APPEND_ENTRIES_RESPONSE.value, "AppendEntriesResponse"):
        return AppendEntriesResponse(
            term=d["term"],
            success=d["success"],
            match_index=d.get("match_index", 0),
        )
    if msg_type in (MessageType.CLIENT_COMMAND.value, "ClientCommand"):
        return ClientCommand(
            op=ClientOp(d["op"]),
            key=d["key"],
            value=d.get("value"),
            request_id=d.get("request_id", ""),
        )
    if msg_type in (MessageType.CLIENT_RESPONSE.value, "ClientResponse"):
        return ClientResponse(
            success=d["success"],
            value=d.get("value"),
            leader_id=d.get("leader_id"),
            error=d.get("error", ""),
            request_id=d.get("request_id", ""),
        )
    raise ValueError(f"Unknown message type: {msg_type}")
