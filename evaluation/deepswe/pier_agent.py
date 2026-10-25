"""DataCurve Pier adapter for subscription-authenticated Grinta.

Load with ``--agent-import-path evaluation.deepswe.pier_agent:Grinta``. Pier is
an optional benchmark dependency and is intentionally not added to Grinta's
normal runtime dependencies.
"""

from __future__ import annotations

import json
import os
import shlex
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any

from pier.agents.installed.base import BaseInstalledAgent
from pier.agents.installed.codex import Codex as PierCodex
from pier.environments.base import BaseEnvironment
from pier.models.agent.context import AgentContext
from pier.models.agent.install import AgentInstallSpec, InstallStep
from pier.models.agent.network import NetworkAllowlist
from pier.models.trial.paths import EnvironmentPaths

from evaluation.deepswe.install_recipe import installation_steps
from evaluation.deepswe.pier_compat import (
    normalize_shell_script_lf,
)


def _install_windows_pier_proxy_lf_shim() -> None:
    """Keep Pier 0.3.1's generated Linux proxy entrypoint executable on Windows."""
    if os.name != 'nt':
        return

    # Pier imports this function directly into the Docker environment module, so
    # patch that bound symbol rather than the definition in agent_setup.
    from pier.environments.docker import docker as pier_docker

    original = pier_docker.write_docker_proxy_compose
    if getattr(original, '_grinta_windows_lf_shim', False):
        return

    @wraps(original)
    def write_docker_proxy_compose_lf(*args: Any, **kwargs: Any) -> Path:
        compose_path = original(*args, **kwargs)
        proxy_dir = kwargs.get('proxy_dir')
        if proxy_dir is None and len(args) >= 2:
            proxy_dir = args[1]
        if proxy_dir is None:
            raise RuntimeError('Pier proxy directory was not supplied')
        normalize_shell_script_lf(Path(proxy_dir) / 'start-squid.sh')
        return compose_path

    write_docker_proxy_compose_lf._grinta_windows_lf_shim = True  # type: ignore[attr-defined]
    pier_docker.write_docker_proxy_compose = write_docker_proxy_compose_lf


_install_windows_pier_proxy_lf_shim()


def _auth_cache_path(raw_path: str) -> Path:
    """Resolve a host credential path before any container operation."""
    path = Path(raw_path).expanduser()
    if not path.is_file():
        raise ValueError(f'CODEX_AUTH_JSON_PATH does not exist: {path}')
    return path


class Grinta(BaseInstalledAgent):
    """Install and run one exact Grinta revision inside a Pier task container."""

    SUPPORTS_ATIF = False
    _REMOTE_CODEX_HOME = PurePosixPath('/tmp/grinta-codex-home')
    _REMOTE_SECRETS = PurePosixPath('/tmp/grinta-secrets')

    def __init__(
        self,
        *args: Any,
        grinta_commit: str,
        grinta_repo: str = 'https://github.com/josephsenior/Grinta-Coding-Agent.git',
        reasoning_effort: str = 'xhigh',
        codex_version: str = '0.150.1',
        prevalidate_startup_health: bool = False,
        allow_tree_sitter_bootstrap: bool = False,
        tree_sitter_languages: str = 'python',
        preserve_task_toolchain: bool = False,
        **kwargs: Any,
    ) -> None:
        if len(grinta_commit) != 40 or any(
            c not in '0123456789abcdef' for c in grinta_commit
        ):
            raise ValueError(
                'grinta_commit must be an exact lowercase 40-character SHA'
            )
        if reasoning_effort not in {'low', 'medium', 'high', 'xhigh', 'max'}:
            raise ValueError(f'Unsupported reasoning effort: {reasoning_effort}')
        self.grinta_commit = grinta_commit
        self.grinta_repo = grinta_repo
        self.reasoning_effort = reasoning_effort
        self.codex_version = codex_version
        self.preserve_task_toolchain = preserve_task_toolchain
        self.prevalidate_startup_health = prevalidate_startup_health
        self.allow_tree_sitter_bootstrap = allow_tree_sitter_bootstrap
        requested_languages = ['python', *tree_sitter_languages.split(',')]
        normalized_languages: list[str] = []
        for language in requested_languages:
            language = language.strip().lower()
            if not language:
                continue
            if not all(
                character.isalnum() or character in {'_', '-', '+'}
                for character in language
            ):
                raise ValueError(f'Invalid tree-sitter language name: {language}')
            if language not in normalized_languages:
                normalized_languages.append(language)
        self.tree_sitter_languages = tuple(normalized_languages)
        kwargs.setdefault('version', grinta_commit)
        super().__init__(*args, **kwargs)

    @staticmethod
    def name() -> str:
        return 'grinta'

    def network_allowlist(self) -> NetworkAllowlist:
        # ChatGPT-authenticated Codex traffic; task browsing/package installs are
        # disabled in Grinta's frozen benchmark config.
        domains = ['.chatgpt.com', '.openai.com']
        if self.allow_tree_sitter_bootstrap:
            # Unreported smoke compatibility only. Linux wheels for
            # tree-sitter-language-pack 1.14.3 lazily fetch parser assets.
            domains.extend(['.github.com', '.githubusercontent.com'])
        return NetworkAllowlist(domains=domains)

    def install_spec(self) -> AgentInstallSpec:
        return AgentInstallSpec(
            agent_name=self.name(),
            version=self.grinta_commit,
            steps=[
                InstallStep(**step)
                for step in installation_steps(
                    grinta_repo=self.grinta_repo,
                    grinta_commit=self.grinta_commit,
                    codex_version=self.codex_version,
                    allow_tree_sitter_bootstrap=self.allow_tree_sitter_bootstrap,
                    tree_sitter_languages=self.tree_sitter_languages,
                    preserve_task_toolchain=self.preserve_task_toolchain,
                )
            ],
        )

    def get_version_command(self) -> str:
        return 'grinta --version 2>/dev/null || true'

    def populate_context_post_run(self, context: AgentContext) -> None:
        manifest_path = self.logs_dir / 'manifest.json'
        if not manifest_path.is_file():
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return
        agent = manifest.get('agent') or {}
        context.n_agent_steps = agent.get('turn_count')
        context.metadata = {
            'grinta_run_status': manifest.get('run_status'),
            'authentication': 'chatgpt_subscription',
            'usage_billed_api': False,
            'api_equivalent_cost_usd': agent.get('cost_usd'),
        }

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        del context  # Pier calls populate_context_post_run after this method.
        if not self.model_name or not self.model_name.startswith('codex/'):
            raise ValueError(
                'model_name must use the subscription-backed codex/ transport'
            )
        raw_auth_path = self._get_env('CODEX_AUTH_JSON_PATH')
        if not raw_auth_path:
            raise ValueError(
                'CODEX_AUTH_JSON_PATH is required; pass the local Codex auth cache '
                'through Pier without copying it into the repository'
            )
        auth_path = _auth_cache_path(raw_auth_path)

        remote_auth = (self._REMOTE_SECRETS / 'auth.json').as_posix()
        remote_home = self._REMOTE_CODEX_HOME.as_posix()
        await self.exec_as_agent(
            environment,
            f'mkdir -p {shlex.quote(remote_home)} {shlex.quote(self._REMOTE_SECRETS.as_posix())} '
            f'{shlex.quote(EnvironmentPaths.agent_dir.as_posix())}',
        )
        await environment.upload_file(auth_path, remote_auth)
        if environment.default_user is not None:
            await self.exec_as_root(
                environment,
                f'chown {environment.default_user} {shlex.quote(remote_auth)}',
            )

        env = {
            'CODEX_HOME': remote_home,
            'PATH': (
                '/tmp/grinta-bin:/root/.local/bin:/usr/local/sbin:/usr/local/bin:'
                '/usr/sbin:/usr/bin:/sbin:/bin'
            ),
        }
        if self.preserve_task_toolchain:
            env.pop('PATH')
        setup = f'ln -sf {shlex.quote(remote_auth)} {shlex.quote(remote_home + "/auth.json")}'
        await self.exec_as_agent(environment, setup, env=env)
        runtime_setup = (
            'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22 >/dev/null; '
            'mkdir -p /tmp/grinta-bin; '
            'ln -sf "$(command -v codex)" /tmp/grinta-bin/codex; '
            'ln -sf "$(command -v node)" /tmp/grinta-bin/node; '
            '/tmp/grinta-bin/codex --version >/dev/null'
        )
        if self.preserve_task_toolchain:
            runtime_setup = (
                'export PATH="$HOME/.local/share/grinta-comparison/codex/bin:$HOME/.local/bin:$PATH"; '
                'mkdir -p /tmp/grinta-bin; '
                'ln -sf "$(command -v codex)" /tmp/grinta-bin/codex; '
                'ln -sf "$(command -v grinta-deepswe)" /tmp/grinta-bin/grinta-deepswe; '
                '/tmp/grinta-bin/codex --version >/dev/null'
            )
        await self.exec_as_agent(environment, runtime_setup, env=env)
        if self.prevalidate_startup_health:
            # Smoke-only compatibility mode: validate the real production check
            # in the task container, then avoid its duplicate invocation during
            # Orchestrator construction. Reported runs leave this disabled.
            health_code = (
                'import json; '
                'from backend.engine.tools.health_check import run_production_health_check; '
                'result = run_production_health_check(raise_on_failure=False); '
                'print(json.dumps(result, sort_keys=True)); '
                "raise SystemExit(0 if result['overall_status'] == 'HEALTHY' else 1)"
            )
            health_command = (
                'python_bin="$(head -n 1 "$(command -v grinta-deepswe)" | cut -c 3-)"; '
                f'"$python_bin" -c {shlex.quote(health_code)}'
            )
            await self.exec_as_agent(environment, health_command, env=env)
            env['GRINTA_SKIP_STARTUP_HEALTH_CHECK'] = '1'
        command = (
            'grinta-deepswe '
            '--workspace . '
            f'--instruction {shlex.quote(instruction)} '
            '--task-id pier-trial '
            f'--grinta-commit {self.grinta_commit} '
            f'--model {shlex.quote(self.model_name)} '
            f'--reasoning-effort {shlex.quote(self.reasoning_effort)} '
            f'--output-dir {shlex.quote(EnvironmentPaths.agent_dir.as_posix())}'
        )
        if self.preserve_task_toolchain:
            command = 'export PATH="/tmp/grinta-bin:$HOME/.local/bin:$PATH"; ' + command
        try:
            await self.exec_as_agent(environment, command, env=env)
        finally:
            # The host auth cache is never copied into trial artifacts.
            await environment.exec(
                command=(
                    f'rm -rf {shlex.quote(self._REMOTE_SECRETS.as_posix())} '
                    f'{shlex.quote(remote_home)}'
                ),
                env=env,
            )


class CodexCli(PierCodex):
    """Pier's native Codex CLI with ChatGPT-subscription network policy.

    Pier's stock adapter defaults its egress policy to ``api.openai.com``.
    Subscription-authenticated Codex uses the ChatGPT Codex endpoint instead,
    so this thin adapter changes only the allowlist while retaining Pier's
    native CLI lifecycle, trajectory parser, and auth-file handling.
    """

    def network_allowlist(self) -> NetworkAllowlist:
        domains = ['.chatgpt.com', '.openai.com']
        for key in ('OPENAI_BASE_URL', 'OPENAI_BASE_API'):
            value = self._get_env(key)
            if value:
                domains.append(value)
        return NetworkAllowlist(domains=domains)

    def populate_context_post_run(self, context: Any) -> None:
        """Normalize Codex JSONL to ASCII before Pier's Windows parser reads it.

        Pier opens the session file with the host locale encoding. Codex emits
        UTF-8, so non-ASCII model text can make metrics collection fail on
        Windows even when the task and verifier succeeded. Escaping JSON text
        keeps the event data identical while making it locale-independent.
        """
        session_dir = self._get_session_dir()
        if session_dir is not None:
            for session_file in session_dir.glob('*.jsonl'):
                try:
                    lines = session_file.read_text(encoding='utf-8').splitlines()
                    normalized = []
                    for line in lines:
                        if not line.strip():
                            normalized.append(line)
                            continue
                        normalized.append(
                            json.dumps(json.loads(line), ensure_ascii=True)
                        )
                    session_file.write_text(
                        '\n'.join(normalized) + '\n', encoding='ascii'
                    )
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
        super().populate_context_post_run(context)
