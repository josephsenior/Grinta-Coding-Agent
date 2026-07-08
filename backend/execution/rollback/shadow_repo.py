"""pygit2-backed shadow repository for fast, unified workspace checkpoints.

Provides a private bare git object-store (``ShadowRepo``) that lives in
``.grinta/shadow_repo/`` -- completely independent of any ``.git`` the
workspace project may or may not have.  Every checkpoint is a pygit2
commit; no subprocess is ever spawned.

Key design decisions
--------------------
* **Stat-cache** (``_stat_cache`` dict) -- ``snapshot()`` calls
  ``os.stat()`` on every workspace file but only re-reads and re-hashes
  the blob when ``(mtime_ns, size)`` changed.  Unchanged files reuse
  the previously stored OID from the cached tree.  The cache is persisted
  as a JSON sidecar so it survives process restarts.
* **No line-ending normalisation** -- ``core.autocrlf`` is forced to
  ``false`` so CRLF content on Windows is stored and restored byte-for-byte.
* **Cross-platform** -- pygit2 ships precompiled wheels (with libgit2
  statically bundled) for Windows (x86/x64/arm64), macOS (Intel + Apple
  Silicon) and Linux (manylinux/musllinux, x86_64/aarch64/ppc64le).
  No C compiler or system ``git`` binary is required.
* **Symlinks skipped** -- mirrors ``workspace_checkpoint.py`` behaviour.
* **Thread-safety** -- a ``threading.Lock`` guards index and stat-cache.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from backend.core.logging.logger import app_logger as logger

# Reserved workspace roots that must never be snapshotted or touched
# during restore -- must stay in sync with workspace_checkpoint._RESERVED_ROOTS.
_RESERVED_ROOTS: frozenset[str] = frozenset({".git", ".grinta"})

_STAT_CACHE_FILENAME = "stat_cache.json"
_SHADOW_DIR_NAME = "shadow_repo"


class ShadowRepoError(RuntimeError):
    """Raised when a shadow-repo operation fails unrecoverably."""


class ShadowRepo:
    """Private in-process git object store for workspace checkpoints.

    Args:
        workspace_root: Absolute path to the workspace being snapshotted.
        shadow_dir: Directory that will hold the bare pygit2 repository and
            the stat-cache sidecar.  Defaults to
            ``<workspace_root>/.grinta/shadow_repo``.

    Example::

        repo = ShadowRepo(workspace_root="/my/project")
        sha = repo.snapshot(label="before change")
        # ... agent makes changes ...
        repo.restore(sha)

    """

    def __init__(
        self,
        workspace_root: str | Path,
        shadow_dir: str | Path | None = None,
    ) -> None:
        import pygit2  # local import keeps module importable even if pygit2 absent

        self._pygit2 = pygit2
        self._workspace_root = Path(workspace_root).resolve()
        if shadow_dir is None:
            self._shadow_dir = self._workspace_root / ".grinta" / _SHADOW_DIR_NAME
        else:
            self._shadow_dir = Path(shadow_dir).resolve()
        self._shadow_dir.mkdir(parents=True, exist_ok=True)

        self._stat_cache_path = self._shadow_dir / _STAT_CACHE_FILENAME
        self._stat_cache: dict[str, tuple[int, int]] = self._load_stat_cache()
        self._blob_cache: dict[str, Any] = {}

        self._lock = threading.Lock()
        self._repo = self._open_or_init_repo()
        logger.debug("ShadowRepo ready at %s", self._shadow_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self, label: str = "") -> str:
        """Snapshot the current workspace state and return a commit SHA.

        Only files whose ``(mtime_ns, size)`` changed since the last call
        are re-read and re-hashed -- everything else reuses the cached blob
        OID.  This makes incremental snapshots very fast even for large repos.

        Args:
            label: Optional human-readable label embedded in the commit message.

        Returns:
            Hex commit SHA string (40 chars).

        Raises:
            ShadowRepoError: If the pygit2 commit creation fails.

        """
        with self._lock:
            try:
                return self._snapshot_locked(label)
            except self._pygit2.GitError as exc:
                raise ShadowRepoError(f"pygit2 snapshot failed: {exc}") from exc

    def restore(
        self,
        commit_sha: str,
        *,
        quarantine_dir: str | Path | None = None,
    ) -> Path | None:
        """Restore workspace to the state captured in *commit_sha*.

        Files absent from the snapshot are **quarantined** (moved aside)
        rather than deleted.  ``_RESERVED_ROOTS`` (.git, .grinta) are
        never touched.

        Args:
            commit_sha: SHA of a commit previously returned by :meth:`snapshot`.
            quarantine_dir: Directory to move extra files into.  If *None*,
                a timestamped sibling inside ``.grinta`` is created.

        Returns:
            Path to the quarantine directory, or *None* if nothing was quarantined.

        Raises:
            ShadowRepoError: If the commit SHA cannot be resolved or restore fails.

        """
        with self._lock:
            try:
                return self._restore_locked(commit_sha, quarantine_dir=quarantine_dir)
            except self._pygit2.GitError as exc:
                raise ShadowRepoError(f"pygit2 restore failed: {exc}") from exc

    def prune(self, keep_shas: set[str]) -> None:
        """Record which SHAs must be preserved (GC deferred to future iteration).

        Args:
            keep_shas: Set of commit SHAs that must not be removed.

        """
        with self._lock:
            logger.debug("ShadowRepo.prune: %d SHAs marked for retention", len(keep_shas))

    # ------------------------------------------------------------------
    # Snapshot internals
    # ------------------------------------------------------------------

    def _snapshot_locked(self, label: str) -> str:
        """Core snapshot logic -- must be called with ``_lock`` held."""
        repo = self._repo
        pygit2 = self._pygit2

        index = pygit2.Index()
        new_cache: dict[str, tuple[int, int]] = {}

        for abs_path_str, rel_posix in self._iter_workspace_files():
            try:
                st = os.stat(abs_path_str)
            except OSError:
                continue

            mtime_ns = st.st_mtime_ns
            size = st.st_size
            new_cache[rel_posix] = (mtime_ns, size)

            cached = self._stat_cache.get(rel_posix)
            if cached is not None and cached == (mtime_ns, size):
                blob_oid = self._blob_cache.get(rel_posix)
                if blob_oid is not None:
                    entry = pygit2.IndexEntry(rel_posix, blob_oid, pygit2.GIT_FILEMODE_BLOB)
                    index.add(entry)
                    continue

            try:
                blob_oid = repo.create_blob_fromdisk(abs_path_str)
            except (pygit2.GitError, OSError) as exc:
                logger.warning("Skipping file %s in shadow snapshot: %s", rel_posix, exc)
                continue

            entry = pygit2.IndexEntry(rel_posix, blob_oid, pygit2.GIT_FILEMODE_BLOB)
            index.add(entry)

        self._stat_cache = new_cache
        self._persist_stat_cache(new_cache)

        tree_oid = index.write_tree(repo)

        parents: list[Any] = []
        try:
            head_ref = repo.references.get("refs/heads/shadow")
            if head_ref is not None:
                parents = [head_ref.peel(pygit2.Commit).id]
        except Exception:  # noqa: BLE001
            pass

        sig = pygit2.Signature("Grinta Shadow", "shadow@grinta.local")
        msg = f"[Grinta] {label}" if label else "[Grinta] snapshot"
        commit_oid = repo.create_commit(
            "refs/heads/shadow",
            sig,
            sig,
            msg,
            tree_oid,
            parents,
        )
        commit_sha = str(commit_oid)

        # Refresh blob cache from the committed tree for future stat-cache hits.
        try:
            tree = repo.get(str(tree_oid))
            self._blob_cache = {}
            if tree is not None:
                self._collect_blobs(tree, "", self._blob_cache)
        except Exception:  # noqa: BLE001
            self._blob_cache = {}

        logger.debug("Shadow snapshot created: %s", commit_sha)
        return commit_sha

    # ------------------------------------------------------------------
    # Restore internals
    # ------------------------------------------------------------------

    def _restore_locked(
        self,
        commit_sha: str,
        *,
        quarantine_dir: str | Path | None,
    ) -> Path | None:
        """Core restore logic -- must be called with ``_lock`` held."""
        pygit2 = self._pygit2
        repo = self._repo

        try:
            commit = repo.get(commit_sha)
        except Exception as exc:  # noqa: BLE001
            raise ShadowRepoError(f"Cannot resolve commit {commit_sha!r}: {exc}") from exc

        if commit is None:
            raise ShadowRepoError(f"Commit not found in shadow repo: {commit_sha!r}")

        tree = commit.peel(pygit2.Tree)

        # Collect all files from the snapshot tree.
        snapshot_files: dict[str, bytes] = {}
        self._walk_tree(tree, "", snapshot_files, repo)

        # Quarantine workspace files absent from snapshot.
        qdir: Path | None = Path(quarantine_dir) if quarantine_dir is not None else None
        qdir = self._quarantine_extras(snapshot_files, qdir)

        # Write snapshot files back to the workspace.
        for rel_posix, blob_data in snapshot_files.items():
            dest = self._workspace_root / rel_posix
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(dest, blob_data)

        # Invalidate stat cache -- workspace state has been rewritten.
        self._stat_cache = {}
        self._blob_cache = {}
        self._persist_stat_cache({})

        return qdir

    def _walk_tree(
        self,
        tree: Any,
        prefix: str,
        out: dict[str, bytes],
        repo: Any,
    ) -> None:
        """Recursively collect ``{rel_posix: blob_bytes}`` from a tree."""
        for entry in tree:
            rel = f"{prefix}{entry.name}" if prefix else entry.name
            if entry.type_str == "blob":
                blob = repo.get(entry.id)
                if blob is not None:
                    out[rel] = bytes(blob.data)
            elif entry.type_str == "tree":
                subtree = repo.get(entry.id)
                if subtree is not None:
                    self._walk_tree(subtree, f"{rel}/", out, repo)

    def _quarantine_extras(
        self,
        snapshot_files: dict[str, bytes],
        quarantine_dir: Path | None,
    ) -> Path | None:
        """Move workspace files not in *snapshot_files* to *quarantine_dir*."""
        snapshot_posix: set[str] = set(snapshot_files.keys())

        for item in sorted(
            self._workspace_root.rglob("*"),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            if not item.exists():
                continue
            if self._is_reserved(item):
                continue
            try:
                rel = item.relative_to(self._workspace_root)
            except ValueError:
                continue
            rel_posix = rel.as_posix()

            if item.is_dir():
                has_child = any(sp.startswith(f"{rel_posix}/") for sp in snapshot_posix)
                if not has_child and rel_posix not in snapshot_posix:
                    quarantine_dir = self._move_to_quarantine(item, rel, quarantine_dir)
                continue

            if rel_posix not in snapshot_posix:
                quarantine_dir = self._move_to_quarantine(item, rel, quarantine_dir)

        return quarantine_dir

    def _move_to_quarantine(
        self,
        source: Path,
        rel: Path,
        quarantine_dir: Path | None,
    ) -> Path:
        if quarantine_dir is None:
            ts = int(time.time())
            quarantine_dir = self._shadow_dir.parent / f"restore_quarantine_{ts}"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        target = quarantine_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"{target.name}.{int(time.time() * 1000)}")
        try:
            shutil.move(str(source), str(target))
        except OSError as exc:
            logger.warning("Failed to quarantine %s: %s", source, exc)
        return quarantine_dir

    # ------------------------------------------------------------------
    # Blob cache helpers
    # ------------------------------------------------------------------

    def _collect_blobs(self, tree: Any, prefix: str, out: dict[str, Any]) -> None:
        """Recursively collect ``{rel_posix: blob_oid}`` from a tree object."""
        for entry in tree:
            rel = f"{prefix}{entry.name}" if prefix else entry.name
            if entry.type_str == "blob":
                out[rel] = entry.id
            elif entry.type_str == "tree":
                subtree = self._repo.get(entry.id)
                if subtree is not None:
                    self._collect_blobs(subtree, f"{rel}/", out)

    # ------------------------------------------------------------------
    # Repo init
    # ------------------------------------------------------------------

    def _open_or_init_repo(self) -> Any:
        """Open an existing shadow repo or initialise a fresh bare one."""
        pygit2 = self._pygit2
        repo_path = str(self._shadow_dir)
        try:
            repo = pygit2.Repository(repo_path)
            logger.debug("Opened existing shadow repo at %s", repo_path)
        except (pygit2.GitError, KeyError):
            repo = pygit2.init_repository(repo_path, bare=True)
            # Disable line-ending normalisation so CRLF files are round-tripped
            # byte-for-byte on Windows.
            repo.config["core.autocrlf"] = "false"
            repo.config["core.eol"] = "lf"
            logger.debug("Initialised new shadow repo at %s", repo_path)

        # Seed blob cache from existing shadow HEAD so the very first snapshot
        # after a process restart can still use the stat-cache.
        try:
            ref = repo.references.get("refs/heads/shadow")
            if ref is not None:
                tree = ref.peel(pygit2.Commit).peel(pygit2.Tree)
                self._collect_blobs(tree, "", self._blob_cache)
        except Exception:  # noqa: BLE001
            pass

        return repo

    # ------------------------------------------------------------------
    # File iteration
    # ------------------------------------------------------------------

    def _iter_workspace_files(self):
        """Yield ``(abs_path_str, rel_posix)`` for every snapshotable file."""
        from backend.engine.tools.ignore_filter import (
            get_ignore_spec,
            is_ignored_file,
            prune_ignored_dirs,
        )

        root = str(self._workspace_root)
        spec = get_ignore_spec(root)

        for dirpath, dirnames, filenames in os.walk(root):
            prune_ignored_dirs(root, dirpath, dirnames, spec)
            for name in filenames:
                if is_ignored_file(root, dirpath, name, spec):
                    continue
                abs_path = os.path.join(dirpath, name)
                if os.path.islink(abs_path):
                    continue
                try:
                    rel = Path(abs_path).relative_to(self._workspace_root)
                except ValueError:
                    continue
                if rel.parts and rel.parts[0] in _RESERVED_ROOTS:
                    continue
                yield abs_path, rel.as_posix()

    # ------------------------------------------------------------------
    # Stat-cache persistence
    # ------------------------------------------------------------------

    def _load_stat_cache(self) -> dict[str, tuple[int, int]]:
        if not self._stat_cache_path.exists():
            return {}
        try:
            raw: dict[str, list[int]] = json.loads(
                self._stat_cache_path.read_text(encoding="utf-8")
            )
            return {k: (int(v[0]), int(v[1])) for k, v in raw.items()}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load shadow stat cache: %s", exc)
            return {}

    def _persist_stat_cache(self, cache: dict[str, tuple[int, int]]) -> None:
        try:
            payload = json.dumps(
                {k: list(v) for k, v in cache.items()},
                separators=(",", ":"),
            )
            tmp = self._stat_cache_path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(str(tmp), str(self._stat_cache_path))
        except OSError as exc:
            logger.warning("Failed to persist shadow stat cache: %s", exc)

    # ------------------------------------------------------------------
    # Reserved-path guard
    # ------------------------------------------------------------------

    def _is_reserved(self, path: Path) -> bool:
        """Return True for .git, .grinta and the shadow-repo dir itself."""
        try:
            rel = path.resolve().relative_to(self._workspace_root)
        except ValueError:
            return True
        if rel.parts and rel.parts[0] in _RESERVED_ROOTS:
            return True
        # Belt-and-suspenders: explicitly protect the shadow dir.
        try:
            path.resolve().relative_to(self._shadow_dir)
            return True
        except ValueError:
            pass
        return False

    # ------------------------------------------------------------------
    # Atomic file write
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_write(dest: Path, data: bytes) -> None:
        """Write *data* to *dest* atomically via a temp file + rename."""
        import tempfile

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{dest.name}.",
            suffix=".tmp",
            dir=str(dest.parent),
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            tmp_path.write_bytes(data)
            os.replace(str(tmp_path), str(dest))
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)


__all__ = ["ShadowRepo", "ShadowRepoError"]
