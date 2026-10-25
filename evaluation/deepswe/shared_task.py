"""Portable shared-task reader and model-free launch contract.

This stdlib-only file is mirrored in Grinta's evaluation/deepswe/shared_task.py.
It verifies inputs; it neither runs commands from a record nor authorizes a model.
"""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def canonical(value):
    return (
        json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
        + '\n'
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_shared_task(path):
    path = Path(path)
    record = json.loads(path.read_bytes())
    claimed = record.pop('spec_sha256')
    if record.get('schema_version') != 1 or record.get('kind') != 'shared-deepswe-task':
        raise ValueError('unsupported shared-task schema')
    if digest(canonical(record)) != claimed:
        raise ValueError('shared-task hash mismatch')
    identity, environment = record['identity'], record['environment']
    if not re.fullmatch(r'[0-9a-f]{40}', identity['base_commit']):
        raise ValueError('shared task requires a full base commit')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', environment['effective_image_id']):
        raise ValueError('shared task requires an immutable image')
    validation = record['public_validation']
    if digest(canonical(validation['command'])) != validation['command_sha256']:
        raise ValueError('public command hash mismatch')
    if digest(canonical(environment['setup'])) != environment['setup_sha256']:
        raise ValueError('setup hash mismatch')
    baseline = validation['baseline']
    name = baseline['native_report_file']
    if name not in ('baseline-report.json', 'baseline-report.xml'):
        raise ValueError('unsupported public report path')
    if digest((path.parent / name).read_bytes()) != baseline['native_report_sha256']:
        raise ValueError('public report hash mismatch')
    if not record['problem']['text'].strip():
        raise ValueError('empty shared instruction')
    record['spec_sha256'] = claimed
    return record


def verify_workspace(record, workspace):
    """Check the prepared checkout, not merely a commit available in its store."""
    workspace = Path(workspace).resolve(strict=True)
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        return subprocess.run(
            [
                'git',
                '-c',
                f'safe.directory={workspace.as_posix()}',
                '-c',
                'core.fsmonitor=false',
                '-c',
                'core.hooksPath=' + os.devnull,
                *args,
            ],
            cwd=workspace,
            env=env,
            check=True,
            capture_output=True,
            timeout=60,
        ).stdout

    identity = record['identity']
    if (
        Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve()
        != workspace
    ):
        raise ValueError('workspace must be the repository root')
    if git('rev-parse', 'HEAD').decode().strip() != identity['base_commit']:
        raise ValueError('workspace base commit mismatch')
    snapshot = identity['source_snapshot']
    if git('rev-parse', 'HEAD^{tree}').decode().strip() != snapshot['git_tree']:
        raise ValueError('workspace tree mismatch')
    if (
        digest(git('ls-tree', '-rz', '--full-tree', 'HEAD'))
        != snapshot['tree_listing_sha256']
    ):
        raise ValueError('workspace source listing mismatch')
    if git('status', '--porcelain', '--untracked-files=all', '--ignored'):
        raise ValueError(
            'shared starting workspace must be clean, including ignored files'
        )


def starting_conditions(record):
    """Common input contract, excluding each method's own prompts and execution loop."""
    return {
        key: record[key]
        for key in (
            'identity',
            'problem',
            'environment',
            'public_validation',
            'edit_contract',
            'timing',
        )
    }


def preflight_manifest(record, workspace, system, implementation_revision):
    verify_workspace(record, workspace)
    conditions = starting_conditions(record)
    return {
        'schema_version': 1,
        'system': system,
        'implementation_revision': implementation_revision,
        'spec_sha256': record['spec_sha256'],
        'starting_conditions': conditions,
        'starting_conditions_sha256': digest(canonical(conditions)),
        'workspace_verified': True,
        'container_observed': False,
        'live_model_calls': 0,
        'model': None,
        'launch_authorized': False,
        'scope': 'prepared Git source and configured starting conditions; not an observed container or capability-enforcement result',
    }
