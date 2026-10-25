"""Bounded runtime installation and fingerprint diagnostic; never calls a model."""

import argparse
import hashlib
import json
import subprocess
import tarfile
import time
import uuid
from pathlib import Path

from evaluation.deepswe.install_recipe import installation_steps
from evaluation.deepswe.shared_task import canonical, load_shared_task

PROBE = r"""
import hashlib,importlib.metadata,json,os,pathlib,shutil,subprocess
tools={}
for name in ('python','go','node','npm','uv','git','curl'):
 path=shutil.which(name)
 if path:
  result=subprocess.run([path,'version' if name=='go' else '--version'],capture_output=True,timeout=20)
  tools[name]={'path':path,'resolved':str(pathlib.Path(path).resolve()),
   'sha256':hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest(),
   'version':(result.stdout+result.stderr).decode(errors='replace').strip()[:1000]}
packages=sorted((d.metadata['Name'],d.version) for d in importlib.metadata.distributions())
dpkg=subprocess.run(['dpkg-query','-W','-f=${Package}=${Version}\n'],capture_output=True,timeout=30)
print(json.dumps({'tools':tools,'python_packages':packages,
 'system_packages_sha256':hashlib.sha256(dpkg.stdout).hexdigest(),
 'environment':{k:os.environ.get(k) for k in ('PATH','HOME','GOPATH','GOMODCACHE','GOFLAGS','PYTHONPATH','NODE_PATH')}}))
"""


def verify_source_archive(archive, commit):
    """Compare every delivered file to the selected local Git objects."""
    root = Path(__file__).resolve().parents[2]
    roots = (
        'backend',
        'evaluation',
        'launch',
        'pyproject.toml',
        'README.md',
        'LICENSE',
    )
    listing = subprocess.check_output(
        ['git', '-C', str(root), 'ls-tree', '-rz', commit, '--', *roots]
    )
    expected = {}
    for entry in listing.split(b'\0'):
        if entry:
            metadata, name = entry.split(b'\t', 1)
            mode, _, oid = metadata.split()
            expected[name.decode()] = (mode.decode(), oid.decode())
    actual = {}
    with tarfile.open(archive) as source:
        for member in source:
            if member.isdir():
                continue
            if member.issym():
                data, mode = member.linkname.encode(), '120000'
            elif member.isfile():
                data = source.extractfile(member).read()
                mode = '100755' if member.mode & 0o111 else '100644'
            else:
                raise ValueError('unsupported source archive member')
            actual[member.name] = (
                mode,
                hashlib.sha1(
                    b'blob ' + str(len(data)).encode() + b'\0' + data
                ).hexdigest(),
            )
    if actual != expected:
        raise ValueError('source archive files differ from the pinned Git commit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shared-task', type=Path, required=True)
    parser.add_argument('--grinta-commit', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=900)
    parser.add_argument('--source-archive', type=Path)
    parser.add_argument(
        '--core-runtime-only',
        action='store_true',
        help='Skip model transport installation for model-free rehearsals',
    )
    args = parser.parse_args()
    record = load_shared_task(args.shared_task)
    if args.output.exists():
        raise ValueError('output must be a new directory')
    args.output.mkdir(parents=True)
    environment = record['environment']
    limits = environment['limits']
    name = 'grinta-runtime-rehearsal-' + uuid.uuid4().hex[:12]
    started = time.monotonic()
    result = {
        'task_id': record['identity']['task_id'],
        'model_calls': 0,
        'parent_image_id': environment['effective_image_id'],
        'grinta_commit': args.grinta_commit,
        'setup_network': 'bridge',
        'status': 'started',
        'container': name,
    }

    def docker(*argv, input_bytes=None, timeout=60):
        remaining = args.timeout_seconds - (time.monotonic() - started)
        return subprocess.run(
            ['docker', *argv],
            input=input_bytes,
            capture_output=True,
            check=True,
            timeout=max(1, min(timeout, remaining)),
        )

    def probe():
        return json.loads(
            docker('exec', '-i', name, 'python', '-', input_bytes=PROBE.encode()).stdout
        )

    try:
        docker(
            'create',
            '--name',
            name,
            '--label',
            'grinta.shared-runtime-rehearsal=true',
            '--network=bridge',
            '--cap-drop=ALL',
            '--security-opt=no-new-privileges',
            f'--memory={limits["memory_mb"]}m',
            f'--memory-swap={limits["memory_mb"]}m',
            f'--cpus={limits["cpus"]}',
            f'--pids-limit={limits["pids_limit"]}',
            '--entrypoint=/bin/sh',
            environment['effective_image_id'],
            '-c',
            'while :; do sleep 1; done',
        )
        docker('start', name)
        before = probe()
        (args.output / 'before.json').write_bytes(canonical(before))
        if args.source_archive:
            archive_bytes = args.source_archive.read_bytes()
            archive_commit = (
                subprocess.check_output(
                    ['git', 'get-tar-commit-id'], input=archive_bytes
                )
                .decode()
                .strip()
            )
            if archive_commit != args.grinta_commit:
                raise RuntimeError(
                    'local source archive does not identify the requested Git commit'
                )
            verify_source_archive(args.source_archive, args.grinta_commit)
            result['source_delivery'] = {
                'mode': 'local Git archive',
                'commit': archive_commit,
                'sha256': hashlib.sha256(archive_bytes).hexdigest(),
            }
            docker(
                'cp',
                str(args.source_archive.resolve()),
                name + ':/tmp/grinta-source.tar',
            )
            docker(
                'exec',
                name,
                'sh',
                '-c',
                'mkdir /tmp/grinta-source && tar -xf /tmp/grinta-source.tar -C /tmp/grinta-source',
            )
        steps = installation_steps(
            grinta_repo='https://github.com/josephsenior/Grinta-Coding-Agent.git',
            grinta_commit=args.grinta_commit,
            codex_version='0.150.1',
            allow_tree_sitter_bootstrap=False,
            tree_sitter_languages=('python', record['identity']['language']),
            preserve_task_toolchain=True,
            grinta_source='/tmp/grinta-source' if args.source_archive else None,
        )
        if args.core_runtime_only:
            steps = steps[:2]
        (args.output / 'installation-steps.json').write_bytes(canonical(steps))
        for index, step in enumerate(steps):
            print(
                f'Runtime installation step {index + 1}/{len(steps)} started',
                flush=True,
            )
            script = args.output / f'step-{index}.sh'
            script.write_bytes((step['run'] + '\n').encode())
            docker('cp', str(script.resolve()), name + ':/tmp/grinta-install.sh')
            with (args.output / f'step-{index}.log').open('wb') as log:
                remaining = max(1, args.timeout_seconds - (time.monotonic() - started))
                completed = subprocess.run(
                    ['docker', 'exec', name, '/bin/bash', '/tmp/grinta-install.sh'],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=remaining,
                )
            if completed.returncode:
                raise RuntimeError(
                    f'installation step {index + 1} failed with exit {completed.returncode}'
                )
        after = probe()
        (args.output / 'after.json').write_bytes(canonical(after))
        result['task_fingerprint_unchanged'] = before == after
        result['changed_sections'] = [
            key for key in before if before[key] != after[key]
        ]
        if before != after:
            raise RuntimeError('runtime installation changed the task fingerprint')
        image_id = docker('commit', name, timeout=180).stdout.decode().strip()
        result.update(
            status='pass',
            prepared_image_id=image_id,
            codex_transport_install_complete=not args.core_runtime_only,
            condition='diagnostic runtime-supplemented image; not registered benchmark readiness',
        )
        print('Runtime installed; task fingerprint preserved.', flush=True)
    except Exception as exc:
        result.update(status='blocked', error=f'{type(exc).__name__}: {exc}')
        print(result['error'], flush=True)
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=60)
        result['seconds'] = round(time.monotonic() - started, 1)
        (args.output / 'result.json').write_bytes(canonical(result))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
