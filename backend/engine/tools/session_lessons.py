"""Persist durable lessons when a session finishes successfully via orchestrator-owned reflection."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from backend.core.logging.logger import app_logger as logger
from backend.ledger import EventSource
from backend.context.memory.project_memory import ProjectMemoryService

def _has_unresolved_tasks(state: Any) -> bool:
    if not getattr(state, 'plan', None):
        return False
    
    def _is_unresolved(step: Any) -> bool:
        if getattr(step, 'status', 'todo') in {'todo', 'in_progress'}:
            return True
        for sub in getattr(step, 'subtasks', []):
            if _is_unresolved(sub):
                return True
        return False
        
    for step in getattr(state.plan, 'steps', []):
        if _is_unresolved(step):
            return True
    return False


def detect_reflection_signals(history: list[Any]) -> list[str]:
    """Scan history for signals of durable memory candidates."""
    signals = []
    
    # 1. Check for file mutations (Create/Edit/Write)
    mutated = False
    for event in history:
        class_name = type(event).__name__
        if 'File' in class_name and ('Edit' in class_name or 'Create' in class_name or 'Write' in class_name):
            mutated = True
            break
    if mutated:
        signals.append("mutation")
        
    # 2. Check for user corrections
    user_correction = False
    for event in history:
        if getattr(event, 'source', None) == EventSource.USER and hasattr(event, 'content'):
            content = str(event.content).lower()
            if any(word in content for word in ["wrong", "mistake", "error", "no, actually", "incorrect", "fix it"]):
                user_correction = True
                break
    if user_correction:
        signals.append("user_correction")
        
    # 3. Check for command failure recovery
    has_failure = False
    recovered = False
    for event in history:
        class_name = type(event).__name__
        if class_name in {'TerminalRunObservation', 'CmdRunObservation', 'RunObservation'}:
            exit_code = getattr(event, 'exit_code', 0)
            if isinstance(exit_code, int) and exit_code != 0:
                has_failure = True
            elif isinstance(exit_code, int) and exit_code == 0 and has_failure:
                recovered = True
    if recovered:
        signals.append("command_recovery")
        
    # 4. Check for platform/quirk keywords in logs
    has_quirk = False
    for event in history:
        if hasattr(event, 'content'):
            content = str(event.content).lower()
            if any(word in content for word in ["windows", "unix", "permission", "workaround", "quirk"]):
                has_quirk = True
                break
    if has_quirk:
        signals.append("platform_quirk")
        
    return signals


def format_history_for_reflection(history: list[Any]) -> str:
    """Format history events into a concise summary for LLM reflection."""
    summary_lines = []
    for event in history:
        class_name = type(event).__name__
        source = getattr(event, 'source', 'unknown')
        if class_name == 'MessageAction':
            summary_lines.append(f"[Message] {source}: {getattr(event, 'content', '')}")
        elif class_name in {'TerminalRunAction', 'CmdRunAction'}:
            summary_lines.append(f"[Command Run] {getattr(event, 'command', '')}")
        elif class_name in {'TerminalRunObservation', 'CmdRunObservation', 'RunObservation'}:
            exit_code = getattr(event, 'exit_code', 0)
            output = getattr(event, 'content', '')
            output_snippet = output[:300] + '...' if len(output) > 300 else output
            summary_lines.append(f"[Command Result] Exit Code: {exit_code}\nOutput: {output_snippet}")
        elif class_name in {'FileEditAction', 'CreateFileAction', 'WriteFileAction'}:
            summary_lines.append(f"[File Mutate] {class_name} on {getattr(event, 'path', '')}")
        elif class_name in {'ErrorObservation', 'RecallFailureObservation'}:
            summary_lines.append(f"[Error] {getattr(event, 'content', '')}")
    return '\n'.join(summary_lines)


async def persist_finish_lessons(
    *,
    summary: str,
    session_id: str | None = None,
    state: Any | None = None,
    controller: Any | None = None,
) -> None:
    """Trigger targeted reflection to extract durable project memories."""
    if not state or not controller:
        return

    # Check unresolved tasks
    if _has_unresolved_tasks(state):
        logger.info("Unresolved tasks exist. Skipping memory reflection.")
        return

    history = getattr(state, 'history', [])
    signals = detect_reflection_signals(history)
    if not signals:
        logger.info("No reflection signals detected. Skipping memory reflection.")
        return

    logger.info("Memory reflection signals detected: %s. Starting targeted reflection.", signals)

    agent = getattr(controller, 'agent', None)
    llm = getattr(agent, 'llm', None)
    if not llm:
        logger.info("No LLM configured on agent. Skipping memory reflection.")
        return

    history_summary = format_history_for_reflection(history)
    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are Grinta's memory reflection service.\n"
                "Analyze the session event history and extract durable, high-confidence project-scoped memories/lessons.\n\n"
                "durable facts include:\n"
                "- build, run, or test commands specific to this repository.\n"
                "- project structure conventions (e.g. where code or tests must be placed).\n"
                "- platform/environment quirks (e.g. cross-platform differences like Windows path issues).\n"
                "- verified failure patterns and their validated fixes.\n\n"
                "DO NOT extract:\n"
                "- Speculative hypotheses that were not verified.\n"
                "- Session summary or transient info (e.g. \"I edited app.py to fix X\").\n"
                "- General Q&A or facts already known globally (e.g. \"Python uses list.append()\").\n"
                "- User preferences (e.g. \"user prefers TOML\").\n\n"
                "Format your response as a JSON object containing a \"candidates\" key with a list of entries.\n"
                "Each candidate must have:\n"
                "- kind: one of \"command\", \"convention\", \"architecture\", \"lesson\", \"strategy\", \"heuristic\", \"decision\"\n"
                "- fact: A clear, concise instruction of what must be done or is true.\n"
                "- evidence: A list of details/strings proving this fact (e.g. successful commands run).\n"
                "- confidence: A float from 0.0 to 1.0. Only return candidates with confidence >= 0.85.\n"
                "- superseded_ids: A list of candidate/memory IDs (if any) this fact replaces.\n\n"
                "JSON format:\n"
                "{\n"
                "  \"candidates\": [\n"
                "    {\n"
                "      \"kind\": \"command\",\n"
                "      \"fact\": \"Run integration tests with uv run pytest backend/tests/integration -q.\",\n"
                "      \"evidence\": [\"Command 'uv run pytest backend/tests/integration -q' passed successfully.\"],\n"
                "      \"confidence\": 0.95,\n"
                "      \"superseded_ids\": []\n"
                "    }\n"
                "  ]\n"
                "}\n"
            )
        },
        {
            "role": "user",
            "content": (
                f"Session Final Summary:\n{summary}\n\n"
                f"Session Event History:\n{history_summary}\n"
            )
        }
    ]

    try:
        response = await llm.completion(messages=prompt_messages, temperature=0.1)
        raw_content = response.content.strip()
        if raw_content.startswith('```'):
            start = raw_content.find('{')
            end = raw_content.rfind('}')
            if start != -1 and end != -1:
                raw_content = raw_content[start:end+1]
        
        data = json.loads(raw_content)
        candidates = data.get('candidates', [])
        if not candidates:
            return

        service = ProjectMemoryService()
        for cand in candidates:
            confidence = cand.get('confidence', 1.0)
            if confidence >= 0.85:
                entry_id = service.upsert_candidate(
                    kind=cand.get('kind', 'lesson'),
                    fact=cand.get('fact', ''),
                    evidence=cand.get('evidence', []),
                    confidence=confidence,
                    source_session=session_id
                )
                logger.info("Upserted project memory candidate: %s -> %s", cand.get('fact', ''), entry_id)
                # handle supersession
                for superseded_id in cand.get('superseded_ids', []):
                    if service.supersede_entry(superseded_id, entry_id):
                        logger.info("Project memory %s superseded by %s", superseded_id, entry_id)
    except Exception as exc:
        logger.warning("Failed to run post-session reflection candidate extraction: %s", exc, exc_info=True)


__all__ = ['persist_finish_lessons']
