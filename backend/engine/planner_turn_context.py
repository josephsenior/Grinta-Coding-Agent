"""Turn-context snapshot helpers for the orchestrator planner."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from backend.context.prompt.turn_context import is_turn_context_text
from backend.core.logging.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.state.state import State

_TURN_CONTEXT_STATE_KEY = '_prompt_turn_context_v1'
_MAX_RECORDED_TURN_CONTEXTS = 64


def message_text(message: dict[str, Any]) -> str:
    content = message.get('content', '')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get('text') or item))
            else:
                parts.append(str(getattr(item, 'text', item)))
        return '\n'.join(part for part in parts if part)
    return str(content)


def _user_message_fingerprint(message: dict[str, Any]) -> str:
    return hashlib.sha256(message_text(message).encode('utf-8')).hexdigest()


def _turn_context_payload(state: State) -> dict[str, Any]:
    extra = getattr(state, 'extra_data', None)
    if not isinstance(extra, dict):
        return {}
    payload = extra.get(_TURN_CONTEXT_STATE_KEY)
    return payload if isinstance(payload, dict) else {}


def _record_lookup(
    messages: list,
) -> tuple[dict[int, tuple[str, int]], int | None]:
    identities: dict[int, tuple[str, int]] = {}
    occurrences: dict[str, int] = {}
    last_user_index: int | None = None
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue
        fingerprint = _user_message_fingerprint(message)
        occurrence = occurrences.get(fingerprint, 0)
        occurrences[fingerprint] = occurrence + 1
        identities[index] = (fingerprint, occurrence)
        last_user_index = index
    return identities, last_user_index


def _turn_context_records(
    pool: dict[str, Any],
    turns: list[Any],
) -> dict[tuple[str, int], list[str]]:
    records: dict[tuple[str, int], list[str]] = {}
    for record in turns:
        if not isinstance(record, dict):
            continue
        fingerprint = record.get('user_fingerprint')
        occurrence = record.get('occurrence')
        block_ids = record.get('block_ids')
        if (
            not isinstance(fingerprint, str)
            or not isinstance(occurrence, int)
            or not isinstance(block_ids, list)
        ):
            continue
        blocks = [pool.get(block_id) for block_id in block_ids]
        records[(fingerprint, occurrence)] = [
            block
            for block in blocks
            if isinstance(block, str) and is_turn_context_text(block)
        ]
    return records


def _restore_turn_context_messages(
    messages: list,
    identities: dict[int, tuple[str, int]],
    records: dict[tuple[str, int], list[str]],
) -> list:
    restored: list = []
    for index, message in enumerate(messages):
        identity = identities.get(index)
        if identity is not None and identity in records:
            while (
                restored
                and isinstance(restored[-1], dict)
                and restored[-1].get('role') == 'system'
                and is_turn_context_text(message_text(restored[-1]))
            ):
                restored.pop()
            restored.extend(
                {'role': 'system', 'content': block}
                for block in records.get(identity, [])
            )
        restored.append(message)
    return restored


def restore_prior_turn_context(
    messages: list,
    state: State,
) -> tuple[list, bool]:
    payload = _turn_context_payload(state)
    pool = payload.get('blocks')
    turns = payload.get('turns')
    if not isinstance(pool, dict) or not isinstance(turns, list):
        return list(messages), False

    records = _turn_context_records(pool, turns)
    identities, last_user_index = _record_lookup(messages)
    if last_user_index is None:
        return list(messages), False
    current_turn_restored = identities[last_user_index] in records
    restored = _restore_turn_context_messages(messages, identities, records)
    return restored, current_turn_restored


def _collect_trailing_turn_context_blocks(
    messages: list,
    last_user_index: int,
) -> list[str]:
    blocks: list[str] = []
    index = last_user_index - 1
    while index >= 0:
        message = messages[index]
        if (
            not isinstance(message, dict)
            or message.get('role') != 'system'
            or not is_turn_context_text(message_text(message))
        ):
            break
        blocks.append(message_text(message))
        index -= 1
    blocks.reverse()
    return blocks


def _turn_context_store(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw_pool = payload.get('blocks')
    raw_turns = payload.get('turns')
    pool = dict(raw_pool) if isinstance(raw_pool, dict) else {}
    turns = (
        [item for item in raw_turns if isinstance(item, dict)]
        if isinstance(raw_turns, list)
        else []
    )
    return pool, turns


def _store_turn_context_blocks(
    pool: dict[str, Any],
    blocks: list[str],
) -> list[str]:
    block_ids: list[str] = []
    for block in blocks:
        block_id = hashlib.sha256(block.encode('utf-8')).hexdigest()
        pool[block_id] = block
        block_ids.append(block_id)
    return block_ids


def _upsert_turn_context_record(
    turns: list[dict[str, Any]],
    identity: tuple[str, int],
    block_ids: list[str],
) -> list[dict[str, Any]]:
    fingerprint, occurrence = identity
    record = {
        'user_fingerprint': fingerprint,
        'occurrence': occurrence,
        'block_ids': block_ids,
    }
    turns = [
        item
        for item in turns
        if (
            item.get('user_fingerprint'),
            item.get('occurrence'),
        )
        != identity
    ]
    turns.append(record)
    return turns[-_MAX_RECORDED_TURN_CONTEXTS:]


def _referenced_turn_context_block_ids(
    turns: list[dict[str, Any]],
) -> set[str]:
    referenced_ids: set[str] = set()
    for item in turns:
        saved_ids = item.get('block_ids')
        if isinstance(saved_ids, list):
            referenced_ids.update(
                block_id for block_id in saved_ids if isinstance(block_id, str)
            )
    return referenced_ids


def _persist_turn_context_payload(
    state: State,
    payload: dict[str, Any],
) -> None:
    extra = getattr(state, 'extra_data', None)
    if isinstance(extra, dict):
        extra[_TURN_CONTEXT_STATE_KEY] = payload
    setter = getattr(state, 'set_extra', None)
    if callable(setter):
        try:
            setter(
                _TURN_CONTEXT_STATE_KEY,
                payload,
                source='OrchestratorPlanner',
            )
        except Exception:
            logger.debug('Failed to persist turn context snapshots', exc_info=True)


def record_current_turn_context(messages: list, state: State) -> None:
    identities, last_user_index = _record_lookup(messages)
    if last_user_index is None:
        return

    blocks = _collect_trailing_turn_context_blocks(messages, last_user_index)
    if not blocks:
        return

    identity = identities[last_user_index]
    pool, turns = _turn_context_store(_turn_context_payload(state))
    block_ids = _store_turn_context_blocks(pool, blocks)
    turns = _upsert_turn_context_record(turns, identity, block_ids)
    referenced_ids = _referenced_turn_context_block_ids(turns)
    new_payload = {
        'blocks': {
            block_id: text
            for block_id, text in pool.items()
            if block_id in referenced_ids and isinstance(text, str)
        },
        'turns': turns,
    }
    _persist_turn_context_payload(state, new_payload)
