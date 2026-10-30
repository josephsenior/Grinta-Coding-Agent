"""Archive exactly one base tree and commit, without future repository history."""

import io
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath


def archive_source(repository, commit, destination):
    environment = {
        k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')
    }
    environment.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')

    def git(root, *args, data=None):
        return subprocess.run(
            ['git', '-c', 'core.hooksPath=' + os.devnull, '-C', str(root), *args],
            input=data,
            capture_output=True,
            check=True,
            timeout=120,
            env=environment,
        ).stdout

    listing = git(repository, 'ls-tree', '-rz', '--full-tree', commit)
    objects = [
        line.split(b' ', 1)[0]
        for line in git(
            repository, 'rev-list', '--objects', commit + '^{tree}'
        ).splitlines()
    ]
    packed = git(
        repository,
        'pack-objects',
        '--stdout',
        data=b'\n'.join([commit.encode(), *objects]) + b'\n',
    )
    with tempfile.TemporaryDirectory(prefix='sealed-pilot-git-') as temporary:
        root = Path(temporary)
        git(root, 'init')
        git(root, 'unpack-objects', data=packed)
        (root / '.git/shallow').write_text(commit + '\n')
        git(root, 'update-ref', 'refs/heads/task-base', commit)
        git(root, 'symbolic-ref', 'HEAD', 'refs/heads/task-base')
        git(root, 'config', 'core.filemode', 'true')
        # Populate tracking metadata without checking out or changing source.
        # Otherwise the extracted tree appears deleted/untracked to Git.
        git(root, 'read-tree', commit)
        with tarfile.open(destination, 'w') as archive:
            archive.add(root / '.git', arcname='.git')
            for entry in listing.split(b'\0'):
                if not entry:
                    continue
                meta, rawname = entry.split(b'\t', 1)
                mode, kind, oid = meta.split()
                name = rawname.decode('utf-8')
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or path.parts[0] == '.git':
                    raise ValueError('unsafe task source path')
                if kind != b'blob' or mode not in (b'100644', b'100755'):
                    raise ValueError('this initial pilot requires regular source files')
                data = git(repository, 'cat-file', 'blob', oid.decode())
                info = tarfile.TarInfo(name)
                info.mode = 0o755 if mode == b'100755' else 0o644
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
