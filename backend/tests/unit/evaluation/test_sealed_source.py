import subprocess
import tarfile

from evaluation.deepswe.sealed_source import archive_source


def test_source_archive_excludes_future_commits(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()

    def git(root, *args, check=True):
        return subprocess.run(
            [
                'git',
                '-c',
                'user.name=Test',
                '-c',
                'user.email=test@example.invalid',
                '-C',
                str(root),
                *args,
            ],
            capture_output=True,
            check=check,
        )

    git(repo, 'init')
    (repo / 'code.py').write_text('base = True\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'base')
    base = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    (repo / 'solution.py').write_text('future = True\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'future')
    future = git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    archive_source(repo, base, tmp_path / 'source.tar')
    extracted = tmp_path / 'extracted'
    with tarfile.open(tmp_path / 'source.tar') as archive:
        archive.extractall(extracted, filter='data')
    assert not (extracted / 'solution.py').exists()
    assert git(extracted, 'rev-parse', 'HEAD').stdout.decode().strip() == base
    assert git(extracted, 'cat-file', '-e', future, check=False).returncode != 0
