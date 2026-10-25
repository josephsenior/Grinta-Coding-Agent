from evaluation.deepswe.install_recipe import installation_steps
from evaluation.deepswe.pier_compat import codex_npm_install_args


def test_codex_install_includes_explicit_linux_binary_alias() -> None:
    args = codex_npm_install_args('0.150.1')

    assert '@openai/codex@0.150.1' in args
    assert '@openai/codex-linux-x64@npm:@openai/codex@0.150.1-linux-x64' in args


def test_shared_installer_preserves_existing_task_tools():
    steps = installation_steps(
        grinta_repo='https://example.invalid/grinta.git',
        grinta_commit='a' * 40,
        codex_version='0.150.1',
        allow_tree_sitter_bootstrap=False,
        tree_sitter_languages=('python', 'go'),
        preserve_task_toolchain=True,
    )
    scripts = '\n'.join(step['run'] for step in steps)
    assert 'apt-get' not in scripts
    assert 'nvm install' not in scripts
    assert '/usr/local/bin/node' not in scripts
    assert 'astral.sh/uv/install.sh' not in scripts
    assert '--prefix "$prefix"' in scripts
    assert scripts.count('prefetch([language])') == 2


def test_legacy_installer_retains_its_original_toolchain_setup():
    steps = installation_steps(
        grinta_repo='https://example.invalid/grinta.git',
        grinta_commit='a' * 40,
        codex_version='0.150.1',
        allow_tree_sitter_bootstrap=False,
        tree_sitter_languages=('python',),
    )
    scripts = '\n'.join(step['run'] for step in steps)
    assert 'apt-get update' in scripts
    assert 'nvm install 22' in scripts
    assert '/usr/local/bin/node' in scripts


def test_shared_pier_profile_preserves_numba_resources_without_host_mounts():
    from evaluation.deepswe.shared_environment import compose_profile

    record = {
        'environment': {
            'network': {'agent_and_candidate_validation': 'none'},
            'user': {'user': 'root'},
            'extra_hosts': {},
            'limits': {
                'memory_mb': 8192,
                'cpus': 2,
                'pids_limit': 2048,
                'swap_policy': 'docker-default',
                'scratch_mode': 'volume',
                'scratch_mb': None,
            },
        }
    }
    main = compose_profile(record, 'sha256:' + 'a' * 64)['services']['main']
    assert main['read_only'] is True
    assert main['network_mode'] == 'none'
    assert main['cap_drop'] == ['ALL']
    assert main['volumes'] == [{'type': 'volume', 'target': '/tmp'}]
    assert main['cpus'] == 2 and main['mem_limit'] == '8192m'
    assert 'memswap_limit' not in main
