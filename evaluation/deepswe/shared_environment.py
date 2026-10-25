"""Explicit Pier Docker profile for a previously prepared shared runtime image."""

import asyncio
import json
import re
import subprocess
from dataclasses import replace
from pathlib import Path, PurePosixPath


def compose_profile(record, runtime_image_id):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', runtime_image_id):
        raise ValueError('shared runtime image must be immutable')
    environment = record['environment']
    limits = environment['limits']
    if environment['network']['agent_and_candidate_validation'] != 'none':
        raise ValueError('shared agent environment must be offline')
    main = {
        'image': runtime_image_id,
        'pull_policy': 'never',
        'network_mode': 'none',
        'read_only': True,
        'cap_drop': ['ALL'],
        'security_opt': ['no-new-privileges'],
        'init': True,
        'user': environment['user']['user'],
        'working_dir': '/tmp',
        'mem_limit': f'{limits["memory_mb"]}m',
        'cpus': limits['cpus'],
        'pids_limit': limits['pids_limit'],
        'deploy': {
            'resources': {
                'limits': {
                    'pids': limits['pids_limit'],
                    'cpus': str(limits['cpus']),
                    'memory': f'{limits["memory_mb"]}m',
                }
            }
        },
        'environment': {
            'PYTHONDONTWRITEBYTECODE': '1',
            'GRINTA_LOG_ROOT': '/tmp/grinta-logs',
        },
        'entrypoint': ['/bin/sh'],
        'command': [
            '-c',
            'mkdir -p /tmp/pier-logs/agent /tmp/pier-logs/verifier /tmp/pier-logs/artifacts; exec sleep infinity',
        ],
    }
    if limits['swap_policy'] == 'disabled':
        main['memswap_limit'] = f'{limits["memory_mb"]}m'
    elif limits['swap_policy'] != 'docker-default':
        raise ValueError('unsupported shared swap policy')
    if limits['scratch_mode'] == 'tmpfs':
        main['tmpfs'] = [
            f'/tmp:rw,exec,nosuid,nodev,size={limits["scratch_mb"]}m,mode=1777'
        ]
    elif limits['scratch_mode'] == 'volume':
        main['volumes'] = [{'type': 'volume', 'target': '/tmp'}]
    else:
        raise ValueError('unsupported shared scratch mode')
    if environment['extra_hosts']:
        main['extra_hosts'] = environment['extra_hosts']
    return {'services': {'main': main}}


def create_shared_environment(
    record, runtime_image_id, directory, trial_directory, session_id
):
    """Use real Pier lifecycle/exec while applying the reviewed shared controls."""
    from pier.environments.docker.docker import DockerEnvironment
    from pier.models.task.config import EnvironmentConfig
    from pier.models.trial.paths import TrialPaths

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    profile_path = directory / 'shared-profile.json'
    profile_path.write_text(
        json.dumps(compose_profile(record, runtime_image_id)), encoding='utf-8'
    )
    (directory / 'Dockerfile').write_text(
        'FROM ' + runtime_image_id + '\n', encoding='utf-8'
    )

    class SharedDockerEnvironment(DockerEnvironment):
        @property
        def _docker_compose_paths(self):
            return [*super()._docker_compose_paths, profile_path]

        async def upload_file(self, source_path, target_path):
            # Docker cp rejects read-only rootfs even for writable tmpfs paths.
            # Stream through exec; never weaken the container for transfer.
            target = PurePosixPath(target_path)
            if target.parts[:2] != ('/', 'tmp') or '..' in target.parts:
                raise ValueError('shared uploads must stay under /tmp')
            container = await self._run_docker_compose_command(
                ['ps', '--quiet', 'main']
            )

            def stream():
                with Path(source_path).open('rb') as source:
                    subprocess.run(
                        [
                            'docker',
                            'exec',
                            '-i',
                            container.stdout.strip(),
                            'sh',
                            '-c',
                            'cat > "$1"',
                            'shared-upload',
                            str(target),
                        ],
                        stdin=source,
                        check=True,
                        capture_output=True,
                        timeout=60,
                    )

            await asyncio.to_thread(stream)

        async def upload_dir(self, source_dir, target_dir):
            raise NotImplementedError(
                'upload a reviewed source archive under /tmp and extract it there'
            )

        async def stop(self, delete):
            # Pier's delete=True also uses --rmi all. These immutable images are
            # shared benchmark inputs, so remove only this session's resources.
            try:
                await self._run_docker_compose_command(
                    ['down', '--volumes', '--remove-orphans']
                )
            finally:
                self._cleanup_resources_compose_file()

    limits = record['environment']['limits']
    environment = SharedDockerEnvironment(
        environment_dir=directory,
        environment_name='grinta-shared',
        session_id=session_id,
        trial_paths=TrialPaths(Path(trial_directory)),
        task_env_config=EnvironmentConfig(
            docker_image=runtime_image_id,
            cpus=limits['cpus'],
            memory_mb=limits['memory_mb'],
            allow_internet=False,
            workdir='/tmp',
        ),
        default_user=record['environment']['user']['user'],
        mounts_json=[],
    )
    logs = PurePosixPath('/tmp/pier-logs')
    environment._env_paths = replace(
        environment._env_paths,
        logs_dir=logs,
        agent_dir=logs / 'agent',
        verifier_dir=logs / 'verifier',
        artifacts_dir=logs / 'artifacts',
    )
    return environment
