"""Utilities and models for loading and instantiating Forge playbooks."""

from __future__ import annotations

import io
import os
import re
from itertools import chain
from pathlib import Path
from typing import ClassVar

import frontmatter
from pydantic import BaseModel, ValidationError

from backend.core.exceptions import PlaybookValidationError
from backend.core.logger import forge_logger as logger
from backend.playbook_engine.types import InputMetadata, PlaybookMetadata, PlaybookType


def _finalize_loaded_playbook(metadata_dict, path):
    """Finalize the loaded playbook metadata by ensuring proper types.

    Args:
        metadata_dict: Dictionary containing playbook metadata.
        path: Path to the playbook file.

    Returns:
        PlaybookMetadata: Finalized metadata object.

    """
    if "version" in metadata_dict and (not isinstance(metadata_dict["version"], str)):
        metadata_dict["version"] = str(metadata_dict["version"])
    try:
        return PlaybookMetadata(**metadata_dict)
    except ValidationError as exc:
        valid_types = {"knowledge", "repo", "task"}
        if metadata_dict.get("type") not in valid_types:
            valid_display = ", ".join(f'"{t}"' for t in sorted(valid_types))
            raise PlaybookValidationError(
                f'Invalid "type" value: "{metadata_dict.get("type")}". Valid types are: {valid_display}'
            ) from exc
        raise PlaybookValidationError(str(exc)) from exc


def _infer_playbook_type(metadata):
    """Infer the playbook type from metadata.

    Args:
        metadata: The playbook metadata.

    Returns:
        PlaybookType: The inferred type of the playbook.

    """
    inferred_type: PlaybookType
    if metadata.inputs:
        inferred_type = PlaybookType.TASK
        trigger = f"/{metadata.name}"
        if not metadata.triggers:
            metadata.triggers = [trigger]
        elif trigger not in metadata.triggers:
            metadata.triggers.append(trigger)
    elif metadata.triggers:
        inferred_type = PlaybookType.KNOWLEDGE
    else:
        inferred_type = PlaybookType.REPO_KNOWLEDGE
    return inferred_type


class BasePlaybook(BaseModel):
    """Base class for all playbooks."""

    name: str
    content: str
    metadata: PlaybookMetadata
    source: str
    type: PlaybookType
    PATH_TO_THIRD_PARTY_PLAYBOOK_NAME: ClassVar[dict[str, str]] = {
        ".cursorrules": "cursorrules",
        "agents.md": "agents",
        "agent.md": "agents",
    }

    @classmethod
    def _handle_third_party(cls, path: Path, file_content: str) -> RepoPlaybook | None:
        playbook_name = cls.PATH_TO_THIRD_PARTY_PLAYBOOK_NAME.get(path.name.lower())
        if playbook_name is not None:
            return RepoPlaybook(
                name=playbook_name,
                content=file_content,
                metadata=PlaybookMetadata(name=playbook_name),
                source=str(path),
                type=PlaybookType.REPO_KNOWLEDGE,
            )
        return None

    @classmethod
    def _resolve_path(cls, path: Path) -> Path:
        """Safely resolve path."""
        try:
            return path.resolve()
        except Exception:
            return Path(path)

    @classmethod
    def _derive_playbook_name(cls, path: Path, playbook_dir: Path) -> str | None:
        """Derive playbook name from path relative to playbook_dir."""
        third_party_name = cls.PATH_TO_THIRD_PARTY_PLAYBOOK_NAME.get(path.name.lower())
        if third_party_name is not None:
            return third_party_name

        # Try relative path
        try:
            rel_path = path.relative_to(playbook_dir).with_suffix("")
            return str(rel_path).replace("\\", "/")
        except Exception:
            pass

        # Try os.path.relpath as fallback
        try:
            rel_str = os.path.relpath(str(path), start=str(playbook_dir))
            rel_str = os.path.splitext(rel_str)[0]
            return rel_str.replace("\\", "/")
        except Exception:
            return None

    @classmethod
    def _load_file_content(cls, path: Path, file_content: str | None) -> str:
        """Load file content from path if not provided."""
        if file_content is not None:
            return file_content
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except PermissionError:
            # Windows NamedTemporaryFile defaults to exclusive access which prevents a second
            # open(, encoding="utf-8") call while the handle is still alive. Tests keep the temporary file open,
            # so we fall back to the Win32 CreateFile API that allows shared reads.
            if os.name == "nt":
                return cls._read_locked_file_windows(path)
            raise

    @staticmethod
    def _read_locked_file_windows(path: Path) -> str:
        """Read a file that may be locked by another handle on Windows."""
        import ctypes
        from ctypes import wintypes

        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x00000001
        FILE_SHARE_WRITE = 0x00000002
        FILE_SHARE_DELETE = 0x00000004
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x00000080
        INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

        kernel32 = ctypes.windll.kernel32
        kernel32.SetLastError(0)
        handle = kernel32.CreateFileW(
            str(path),
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            error = ctypes.GetLastError()
            raise PermissionError(
                f"Unable to open locked file {path}: error {error}"
            )  # pragma: no cover
        try:
            import msvcrt

            fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
        except Exception:
            kernel32.CloseHandle(handle)
            raise
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as file_obj:
            return file_obj.read()

    @classmethod
    def _create_playbook_instance(
        cls,
        derived_name: str | None,
        content: str,
        metadata: PlaybookMetadata,
        path: Path,
        inferred_type: PlaybookType,
    ) -> BasePlaybook:
        """Create appropriate playbook instance based on type."""
        subclass_map = {
            PlaybookType.KNOWLEDGE: KnowledgePlaybook,
            PlaybookType.REPO_KNOWLEDGE: RepoPlaybook,
            PlaybookType.TASK: TaskPlaybook,
        }

        if inferred_type not in subclass_map:
            msg = f"Could not determine playbook type for: {path}"
            raise ValueError(msg)

        agent_name = derived_name if derived_name is not None else metadata.name
        agent_class = subclass_map[inferred_type]
        return agent_class(
            name=agent_name,
            content=content,
            metadata=metadata,
            source=str(path),
            type=inferred_type,
        )

    @classmethod
    def load(
        cls,
        path: str | Path,
        playbook_dir: Path | None = None,
        file_content: str | None = None,
    ) -> BasePlaybook:
        """Load a playbook from a markdown file with frontmatter.

        The agent's name is derived from its path relative to the playbook_dir.
        """
        path = Path(path) if isinstance(path, str) else path
        path = cls._resolve_path(path)

        # Derive name from directory structure
        derived_name = None
        if playbook_dir is not None:
            playbook_dir = cls._resolve_path(playbook_dir)
            derived_name = cls._derive_playbook_name(path, playbook_dir)

        # Load file content
        file_content = cls._load_file_content(path, file_content)

        # Handle third-party agents
        third_party_agent = cls._handle_third_party(path, file_content)
        if third_party_agent is not None:
            return third_party_agent

        # Parse frontmatter and create playbook
        file_io = io.StringIO(file_content)
        loaded = frontmatter.load(file_io)
        content = loaded.content
        metadata_dict = loaded.metadata or {}
        if "version" in metadata_dict and (
            not isinstance(metadata_dict["version"], str)
        ):
            metadata_dict["version"] = str(metadata_dict["version"])
        metadata = _finalize_loaded_playbook(metadata_dict, path)
        inferred_type = _infer_playbook_type(metadata)

        return cls._create_playbook_instance(
            derived_name, content, metadata, path, inferred_type
        )


class KnowledgePlaybook(BasePlaybook):
    """Knowledge playbooks provide specialized expertise that's triggered by keywords in conversations.

    They help with:
    - Language best practices
    - Framework guidelines
    - Common patterns
    - Tool usage
    """

    def __init__(self, **data) -> None:
        """Validate that the knowledge agent has an appropriate type before initialization."""
        super().__init__(**data)
        if self.type not in [PlaybookType.KNOWLEDGE, PlaybookType.TASK]:
            msg = "KnowledgePlaybook must have type KNOWLEDGE or TASK"
            raise ValueError(msg)

    def match_trigger(self, message: str) -> str | None:
        """Match a trigger in the message.

        Uses a two-tier strategy:
        1. Fast substring match (exact keyword containment).
        2. Lightweight semantic match using word-overlap similarity,
           activated only when no substring match is found.

        Returns the first matching trigger, or None.
        """
        message_lower = message.lower()

        # Tier 1: exact substring (fast path)
        for trigger in self.triggers:
            if trigger.lower() in message_lower:
                return trigger

        # Tier 2: word-overlap similarity (lightweight semantic fallback)
        threshold = 0.55
        message_words = set(re.findall(r"\w+", message_lower))
        if not message_words:
            return None

        best_trigger: str | None = None
        best_score: float = 0.0

        for trigger in self.triggers:
            trigger_words = set(re.findall(r"\w+", trigger.lower()))
            if not trigger_words:
                continue
            # Jaccard-like similarity weighted toward trigger coverage
            overlap = message_words & trigger_words
            if not overlap:
                continue
            # How much of the trigger's vocabulary appears in the message
            coverage = len(overlap) / len(trigger_words)
            # Penalise very short triggers (single-word) to reduce false positives
            length_bonus = min(1.0, len(trigger_words) / 2)
            score = coverage * length_bonus
            if score > best_score:
                best_score = score
                best_trigger = trigger

        if best_score >= threshold:
            return best_trigger

        return None

    @property
    def triggers(self) -> list[str]:
        """Return list of trigger strings associated with this playbook."""
        return self.metadata.triggers


class RepoPlaybook(BasePlaybook):
    """Playbook specialized for repository-specific knowledge and guidelines.

    RepoPlaybooks are loaded from `.Forge/playbooks/repo.md` files within repositories
    and contain private, repository-specific instructions that are automatically loaded when
    working with that repository. They are ideal for:
        - Repository-specific guidelines
        - Team practices and conventions
        - Project-specific workflows
        - Custom documentation references
    """

    def __init__(self, **data) -> None:
        """Ensure repository playbooks are instantiated with repo knowledge type."""
        super().__init__(**data)
        if self.type != PlaybookType.REPO_KNOWLEDGE:
            msg = f"RepoPlaybook initialized with incorrect type: {self.type}"
            raise ValueError(msg)


class TaskPlaybook(KnowledgePlaybook):
    """TaskPlaybook is a special type of KnowledgePlaybook that requires user input.

    These playbooks are triggered by a special format: "/{agent_name}"
    and will prompt the user for any required inputs before proceeding.
    """

    content: str

    def __init__(self, **data) -> None:
        """Validate task-specific type and append prompts for missing user input."""
        super().__init__(**data)
        if self.type != PlaybookType.TASK:
            msg = f"TaskPlaybook initialized with incorrect type: {self.type}"
            raise ValueError(msg)
        self._append_missing_variables_prompt()

    def _append_missing_variables_prompt(self) -> None:
        """Append a prompt to ask for missing variables."""
        if not self.requires_user_input() and (not self.metadata.inputs):
            return
        prompt = "\\n\\nIf the user didn't provide any of these variables, ask the user to provide them first before the agent can proceed with the task."
        content = getattr(self, "content", "")
        setattr(self, "content", content + prompt)

    def extract_variables(self, content: str) -> list[str]:
        """Extract variables from the content.

        Variables are in the format ${variable_name}.
        """
        pattern = "\\$\\{([a-zA-Z_][a-zA-Z0-9_]*)\\}"
        return re.findall(pattern, content)

    def requires_user_input(self) -> bool:
        """Check if this playbook requires user input.

        Returns True if the content contains variables in the format ${variable_name}.
        """
        content = getattr(self, "content", "")
        variables = self.extract_variables(content)
        logger.debug("This playbook requires user input: %s", variables)
        return variables

    @property
    def inputs(self) -> list[InputMetadata]:
        """Get the inputs for this playbook."""
        return self.metadata.inputs


def _collect_special_files(repo_root: Path) -> list[Path]:
    """Collect special configuration files from the repository root.

    Args:
        repo_root: The repository root path.

    Returns:
        list[Path]: List of special files found.

    """
    special_files = []

    # Add .cursorrules if it exists
    if (repo_root / ".cursorrules").exists():
        special_files.append(repo_root / ".cursorrules")

    # Add agents markdown files if they exist
    for agents_filename in ["AGENTS.md", "agents.md", "AGENT.md", "agent.md"]:
        agents_path = repo_root / agents_filename
        if agents_path.exists():
            special_files.append(agents_path)
            break

    return special_files


def _collect_markdown_files(playbook_dir: Path) -> list[Path]:
    """Collect markdown files from the playbook directory.

    Args:
        playbook_dir: The playbook directory path.

    Returns:
        list[Path]: List of markdown files found.

    """
    if not playbook_dir.exists():
        return []

    return [f for f in playbook_dir.rglob("*.md") if f.name != "README.md"]


def _load_single_playbook(file: Path, playbook_dir: Path) -> BasePlaybook:
    """Load a single playbook from a file.

    Args:
        file: The file path to load from.
        playbook_dir: The playbook directory path.

    Returns:
        BasePlaybook: The loaded playbook.

    Raises:
        PlaybookValidationError: If validation fails.
        ValueError: If loading fails.

    """
    try:
        return BasePlaybook.load(file, playbook_dir)
    except PlaybookValidationError as e:
        error_msg = f"Error loading playbook from {file}: {e!s}"
        raise PlaybookValidationError(error_msg) from e
    except ValidationError as e:
        error_msg = f"Error loading playbook from {file}: {e!s}"
        raise PlaybookValidationError(error_msg) from e
    except Exception as e:
        error_msg = f"Error loading playbook from {file}: {e!s}"
        raise ValueError(error_msg) from e


def _categorize_agent(agent: BasePlaybook) -> tuple[str, BasePlaybook]:
    """Categorize an agent by its type.

    Args:
        agent: The agent to categorize.

    Returns:
        tuple[str, BasePlaybook]: Agent type and the agent itself.

    """
    if isinstance(agent, RepoPlaybook):
        return ("repo", agent)
    if isinstance(agent, KnowledgePlaybook):
        return ("knowledge", agent)
    return ("unknown", agent)


def load_playbooks_from_dir(
    playbook_dir: str | Path,
) -> tuple[dict[str, RepoPlaybook], dict[str, KnowledgePlaybook]]:
    """Load all playbooks from the given directory.

    Args:
        playbook_dir: Path to the playbooks directory (e.g. .Forge/playbooks)

    Returns:
        tuple[dict[str, RepoPlaybook], dict[str, KnowledgePlaybook]]: Tuple of (repo_agents, knowledge_agents) dictionaries

    """
    if isinstance(playbook_dir, str):
        playbook_dir = Path(playbook_dir)

    repo_agents: dict[str, RepoPlaybook] = {}
    knowledge_agents: dict[str, KnowledgePlaybook] = {}
    logger.debug("Loading agents from %s", playbook_dir)

    # Collect files to process
    repo_root = playbook_dir.parent.parent
    special_files = _collect_special_files(repo_root)
    md_files = _collect_markdown_files(playbook_dir)

    # Load agents from all files
    for file in chain(special_files, md_files):
        agent = _load_single_playbook(file, playbook_dir)
        agent_type, categorized_agent = _categorize_agent(agent)

        if agent_type == "repo" and isinstance(categorized_agent, RepoPlaybook):
            repo_agents[categorized_agent.name] = categorized_agent
        elif agent_type == "knowledge" and isinstance(
            categorized_agent, KnowledgePlaybook
        ):
            knowledge_agents[categorized_agent.name] = categorized_agent

    logger.debug(
        "Loaded %s playbooks: %s",
        len(repo_agents) + len(knowledge_agents),
        [*repo_agents.keys(), *knowledge_agents.keys()],
    )
    return (repo_agents, knowledge_agents)
