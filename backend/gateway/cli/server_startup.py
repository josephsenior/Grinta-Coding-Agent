"""Canonical local server startup planning and execution helpers."""

from __future__ import annotations

import os
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, MutableMapping

from backend.core.app_paths import get_app_settings_root


@dataclass(slots=True)
class ServerStartupPlan:
    """Resolved startup configuration for the local application server."""

    host: str
    requested_port: int
    resolved_port: int
    port_auto_switched: bool
    reload_enabled: bool
    runtime: str
    project_root: str
    cwd: str
    app_root: str
    settings_path: str
    dotenv_local_loaded: bool
    agent_config_present: bool
    ui_url: str
    api_url: str
    docs_url: str
    health_url: str

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable startup snapshot."""
        return asdict(self)


def ensure_utf8_stdout() -> None:
    """Force UTF-8 stdout when supported so Windows terminals do not crash."""
    stdout_encoding = getattr(sys.stdout, "encoding", None)
    if isinstance(stdout_encoding, str) and stdout_encoding.lower() != "utf-8":
        try:
            cast_stdout: Any = sys.stdout
            cast_stdout.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass


def add_project_root_to_path(project_root: Path) -> None:
    """Ensure the repo root is importable."""
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


def _find_available_port(host_ip: str, preferred_port: int, max_offset: int = 20) -> int:
    """Return preferred_port if free, otherwise the next available port."""
    for offset in range(max_offset + 1):
        candidate = preferred_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host_ip, candidate))
                return candidate
            except OSError:
                continue
    return preferred_port


def load_dotenv_local(
    project_root: Path,
    environ: MutableMapping[str, str] | None = None,
) -> bool:
    """Load .env.local values if present.

    Only fills missing or blank environment variables so explicit operator input wins.
    """
    env = environ if environ is not None else os.environ
    dotenv_path = project_root / ".env.local"
    if not dotenv_path.exists():
        return False

    loaded = False
    with dotenv_path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            existing = env.get(key)
            if existing is None or not str(existing).strip():
                env[key] = value
                loaded = True
    return loaded


def validate_storage_contract(environ: MutableMapping[str, str] | None = None) -> None:
    """Fail fast when database-backed storage is requested without a database URL."""
    env = environ if environ is not None else os.environ
    storage_mode = env.get("APP_KB_STORAGE_TYPE", "file").strip().lower()
    if storage_mode not in {"database", "db"}:
        return
    db_url = env.get("DATABASE_URL", "").strip()
    if db_url:
        return

    print("ERROR: APP_KB_STORAGE_TYPE is set to database but DATABASE_URL is empty.")
    print("Set DATABASE_URL or switch APP_KB_STORAGE_TYPE=file for emergency local fallback.")
    raise SystemExit(2)


def _parse_port(raw: str | None, default: int = 3000) -> int:
    try:
        return int((raw or "").strip() or str(default))
    except (TypeError, ValueError):
        return default


def build_server_startup_plan(
    project_root: Path,
    environ: MutableMapping[str, str] | None = None,
) -> ServerStartupPlan:
    """Resolve the canonical local-server startup plan."""
    env = environ if environ is not None else os.environ
    dotenv_loaded = load_dotenv_local(project_root, env)

    env.setdefault("APP_RUNTIME", "local")
    env.setdefault("APP_LLM_STEP_TIMEOUT_SECONDS", "180")
    env.setdefault("APP_LLM_FIRST_CHUNK_TIMEOUT_SECONDS", "25")

    host = env.get("APP_HOST", env.get("HOST", "127.0.0.1")).strip() or "127.0.0.1"
    requested_port = _parse_port(env.get("APP_PORT") or env.get("PORT"), default=3000)
    resolved_port = _find_available_port(host, requested_port)

    env["APP_PORT"] = str(resolved_port)
    env["PORT"] = str(resolved_port)

    dev_mode = env.get("APP_ENV", "development") != "production"
    watch_enabled = env.get("APP_WATCH", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    reload_enabled = dev_mode and watch_enabled and sys.platform != "win32"

    app_root = Path(get_app_settings_root()).resolve()
    app_root.mkdir(parents=True, exist_ok=True)
    cwd = Path.cwd().resolve()
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::", "::0"} else host

    return ServerStartupPlan(
        host=host,
        requested_port=requested_port,
        resolved_port=resolved_port,
        port_auto_switched=resolved_port != requested_port,
        reload_enabled=reload_enabled,
        runtime=env.get("APP_RUNTIME", "local"),
        project_root=str(project_root.resolve()),
        cwd=str(cwd),
        app_root=str(app_root),
        settings_path=str(app_root / "settings.json"),
        dotenv_local_loaded=dotenv_loaded,
        agent_config_present=(cwd / "agent.yaml").exists(),
        ui_url=f"http://{display_host}:{resolved_port}",
        api_url=f"http://{display_host}:{resolved_port}/api",
        docs_url=f"http://{display_host}:{resolved_port}/docs",
        health_url=f"http://{display_host}:{resolved_port}/api/health/ready",
    )


def record_startup_snapshot(plan: ServerStartupPlan) -> None:
    """Persist the startup plan for operator-facing diagnostics."""
    from backend.gateway.app_state import get_app_state

    get_app_state().record_startup_snapshot(plan.snapshot())


def print_server_startup_preflight(
    plan: ServerStartupPlan,
    emit: Callable[[str], None] = print,
) -> None:
    """Print a concise startup preflight summary for operators."""
    emit("Local server preflight")
    emit(f"  app root: {plan.app_root}")
    emit(f"  settings: {plan.settings_path}")
    emit(f"  cwd: {plan.cwd}")
    emit(f"  runtime: {plan.runtime}")
    emit(f"  host: {plan.host}")
    if plan.port_auto_switched:
        emit(
            f"  port: {plan.requested_port} requested, {plan.resolved_port} selected automatically"
        )
    else:
        emit(f"  port: {plan.resolved_port}")
    emit(f"  reload: {'enabled' if plan.reload_enabled else 'disabled'}")
    emit(f"  .env.local: {'loaded' if plan.dotenv_local_loaded else 'not found'}")
    emit(f"  agent.yaml in cwd: {'yes' if plan.agent_config_present else 'no'}")
    emit(f"  health: {plan.health_url}")
    emit("")
    emit(f"Starting server on {plan.ui_url}")
    emit("Press Ctrl+C to stop the server.")
    emit("")


def run_server_plan(plan: ServerStartupPlan) -> None:
    """Execute the resolved startup plan with uvicorn."""
    import uvicorn

    uvicorn.run(
        "backend.gateway.socketio_asgi_app:app",
        host=plan.host,
        port=plan.resolved_port,
        log_level="info",
        reload=plan.reload_enabled,
        reload_excludes=["./workspace"],
        ws="websockets-sansio",
    )