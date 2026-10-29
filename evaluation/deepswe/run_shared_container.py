"""Explicit shared-container pilot runner with host-only subscription inference."""

import argparse
import json
import secrets
import subprocess
import tarfile
from pathlib import Path

from backend.inference.comparison_budget import AttemptBudget
from evaluation.deepswe.sealed_source import archive_source
from evaluation.deepswe.shared_task import load_shared_task
from evaluation.deepswe.subscription_relay import relay


def run(args):
    record = load_shared_task(args.shared_task)
    task_id = record['identity']['task_id']
    registry = json.loads(args.runtime_registry.read_bytes())
    binding = registry['task_bindings'][task_id]
    evidence = json.loads(args.runtime_evidence.read_bytes())
    from evaluation.deepswe.runtime_binding import verified_runtime

    image = verified_runtime(record, registry, evidence)
    if args.output.exists():
        raise ValueError('output must be a new directory')
    args.output.mkdir(parents=True)
    archive_source(
        args.source_repository,
        record['identity']['base_commit'],
        args.output / 'source.tar',
    )
    name = 'shared-pilot-' + secrets.token_hex(6)
    marker = 'GRINTA_MODEL_' + secrets.token_hex(16) + ':'
    budget = AttemptBudget()
    limits = record['environment']['limits']
    if limits['scratch_mode'] != 'tmpfs' or limits['swap_policy'] != 'disabled':
        raise ValueError(
            'initial pilot runner requires the reviewed tmpfs/no-swap profile'
        )
    command = [
        'docker',
        'run',
        '-d',
        '--name',
        name,
        '--init',
        '--network',
        'none',
        '--read-only',
        '--cap-drop',
        'ALL',
        '--security-opt',
        'no-new-privileges',
        '--memory',
        f'{limits["memory_mb"]}m',
        '--memory-swap',
        f'{limits["memory_mb"]}m',
        '--cpus',
        str(limits['cpus']),
        '--pids-limit',
        str(limits['pids_limit']),
        '--tmpfs',
        f'/tmp:rw,exec,nosuid,nodev,size={limits["scratch_mb"]}m,mode=1777',
        '--user',
        record['environment']['user']['user'],
        '--workdir',
        '/tmp',
        '--env',
        'PYTHONDONTWRITEBYTECODE=1',
        '--env',
        'GRINTA_LOG_ROOT=/tmp/grinta-logs',
        '--env',
        'APP_ROOT=/tmp/grinta-app',
        '--entrypoint',
        '/bin/sh',
        image,
        '-c',
        'exec sleep infinity',
    ]

    def docker(*argv, data=None, timeout=60):
        return subprocess.run(
            ['docker', *argv],
            input=data,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout

    result = {
        'task_id': task_id,
        'spec_sha256': record['spec_sha256'],
        'image_id': image,
        'status': 'setup',
        'grinta_revision': binding['grinta_commit'],
    }
    try:
        docker(*command[1:])
        observed = json.loads(docker('inspect', name))[0]
        (args.output / 'container.json').write_text(json.dumps(observed, indent=2))
        docker(
            'exec',
            '-i',
            name,
            'sh',
            '-c',
            'mkdir -p /tmp/work /tmp/grinta-app; tar -xf - -C /tmp/work',
            data=(args.output / 'source.tar').read_bytes(),
        )
        actual = (
            docker('exec', name, 'git', '-C', '/tmp/work', 'rev-parse', 'HEAD')
            .decode()
            .strip()
        )
        tree = docker(
            'exec',
            name,
            'git',
            '-C',
            '/tmp/work',
            'ls-tree',
            '-rz',
            '--full-tree',
            'HEAD',
        )
        import hashlib

        if (
            actual != record['identity']['base_commit']
            or hashlib.sha256(tree).hexdigest()
            != record['identity']['source_snapshot']['tree_listing_sha256']
        ):
            raise ValueError('container source does not match pinned task')
        baseline = subprocess.run(
            ['docker', 'exec', name, *record['public_validation']['command']['argv']],
            capture_output=True,
            timeout=record['timing']['public_command_timeout_seconds'],
            check=False,
        )
        (args.output / 'baseline.stdout.log').write_bytes(baseline.stdout)
        (args.output / 'baseline.stderr.log').write_bytes(baseline.stderr)
        report = record['public_validation']['command']['report']['path']
        (args.output / 'baseline-report.xml').write_bytes(
            docker('exec', name, 'cat', report)
        )
        if baseline.returncode:
            raise ValueError('initial public baseline failed')
        config = json.loads(Path(__file__).with_name('config.json').read_bytes())
        config['security']['comparison_edit_profile'] = 'agentless-ml-v1'
        config['cache_dir'] = '/tmp/grinta-cache'
        config['file_store_path'] = '/tmp/grinta-store'
        for filename, data in [
            ('config.json', json.dumps(config).encode()),
            ('instruction.txt', record['problem']['text'].encode()),
        ]:
            docker(
                'exec',
                '-i',
                name,
                'sh',
                '-c',
                'cat > "$1"',
                'pilot-upload',
                '/tmp/' + filename,
                data=data,
            )
        if args.prepare_only:
            result['status'] = 'setup_verified'
            return 0
        argv = [
            'docker',
            'exec',
            '-i',
            '-e',
            'GRINTA_SUBSCRIPTION_STDIO=' + marker,
            name,
            '/root/.local/share/uv/tools/grinta/bin/python',
            '-u',
            '-m',
            'evaluation.deepswe.run_grinta',
            '--workspace',
            '/tmp/work',
            '--instruction-file',
            '/tmp/instruction.txt',
            '--task-id',
            task_id,
            '--grinta-commit',
            binding['grinta_commit'],
            '--model',
            'chatgpt-plan/gpt-6.1-sol',
            '--reasoning-effort',
            'medium',
            '--pilot-budget',
            '--config',
            '/tmp/config.json',
            '--output-dir',
            '/tmp/pilot-output',
        ]
        with (args.output / 'agent.log').open('w', encoding='utf-8') as log:
            code = relay(argv, marker=marker, budget=budget, log=log)
        result.update(
            status='completed' if code == 0 else 'agent_error', exit_code=code
        )
        payload = docker(
            'exec', name, 'tar', '-C', '/tmp/pilot-output', '-cf', '-', '.'
        )
        (args.output / 'agent-artifacts.tar').write_bytes(payload)
        import io

        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            archive.extractall(args.output / 'agent', filter='data')
    except Exception as exc:
        result.update(status='failed', error_type=type(exc).__name__, error=str(exc))
    finally:
        result['attempt_budget'] = budget.snapshot()
        (args.output / 'result.json').write_text(json.dumps(result, indent=2))
        subprocess.run(
            ['docker', 'rm', '-f', '-v', name],
            capture_output=True,
            check=False,
            timeout=30,
        )
    print(json.dumps(result))
    return 0 if result['status'] == 'completed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        'shared-task',
        'source-repository',
        'runtime-registry',
        'runtime-evidence',
        'output',
    ):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument(
        '--prepare-only',
        action='store_true',
        help='Verify source and public baseline without model calls',
    )
    raise SystemExit(run(parser.parse_args()))


if __name__ == '__main__':
    main()
