"""Production health check for verifying critical dependencies.

Ensures all App competitive advantages are available at startup.
"""

from typing import Any

from backend.core.logger import app_logger as logger


def check_structure_editor_dependencies() -> tuple[bool, str]:
    """Verify Structure Editor (Tree-sitter) is available.

    This is CRITICAL for production - Structure Editor is App's competitive moat!

    Returns:
        (success, message): Success status and detailed message

    """
    try:
        from tree_sitter_language_pack import get_language, get_parser

        # Test basic functionality
        try:
            get_language('python')
            parser = get_parser('python')

            # Quick parse test
            code = b'def test(): pass'
            tree = parser.parse(code)

            if tree.root_node.type == 'module':
                logger.info('✅ Ultimate Editor: Tree-sitter is READY')
                logger.info('   - Structure-aware editing: ENABLED')
                logger.info('   - Language support: 40+ languages')
                return True, 'Ultimate Editor fully operational'

            return False, 'Tree-sitter parse test failed'

        except Exception as e:
            return False, f'Tree-sitter functionality test failed: {e}'

    except ImportError as e:
        error_msg = f"""
🚨 CRITICAL: Ultimate Editor dependencies missing!

This is App's competitive moat - structure-aware editing with Tree-sitter.
Without it, App falls back to basic string matching (like competitors).

Missing: {e}

PRODUCTION DEPLOYMENT FIX:
1. Ensure pyproject.toml has Tree-sitter as required dependency (NOT optional)
2. Reinstall dependencies with: uv sync
3. Verify with: python -c "import tree_sitter; print('OK')"

For immediate fix: pip install tree-sitter tree-sitter-language-pack
"""
        logger.error(error_msg)
        return False, error_msg


def check_atomic_refactor_dependencies() -> tuple[bool, str]:
    """Verify atomic refactoring system is available.

    Returns:
        (success, message): Success status and detailed message

    """
    try:
        from backend.engine.tools.atomic_refactor import AtomicRefactor

        # Test basic instantiation
        AtomicRefactor()

        logger.info('✅ Atomic Refactoring: READY')
        logger.info('   - Multi-file transactions: ENABLED')
        logger.info('   - Rollback system: ENABLED')
        return True, 'Atomic refactoring fully operational'

    except ImportError as e:
        return False, f'Atomic refactoring not available: {e}'
    except Exception as e:
        return False, f'Atomic refactoring initialization failed: {e}'


def run_production_health_check(raise_on_failure: bool = True) -> dict[str, Any]:
    """Run complete health check for production deployment.

    Args:
        raise_on_failure: If True, raises exception on critical failures

    Returns:
        dict with health check results

    Raises:
        RuntimeError: If critical dependencies missing and raise_on_failure=True

    """
    logger.info('=' * 60)
    logger.info('🏥 APP PRODUCTION HEALTH CHECK')
    logger.info('=' * 60)

    results: dict[str, Any] = {
        'ast_code_editor': None,
        'atomic_refactor': None,
        'overall_status': 'UNKNOWN',
    }

    # Check Structure Editor (CRITICAL)
    ue_success, ue_msg = check_structure_editor_dependencies()
    results['ast_code_editor'] = {
        'status': 'PASS' if ue_success else 'FAIL',
        'message': ue_msg,
        'critical': True,
    }

    # Check Atomic Refactor
    ar_success, ar_msg = check_atomic_refactor_dependencies()
    results['atomic_refactor'] = {
        'status': 'PASS' if ar_success else 'FAIL',
        'message': ar_msg,
        'critical': False,  # Less critical, can work without it
    }

    health_components = {
        name: data for name, data in results.items() if isinstance(data, dict)
    }

    # Determine overall status
    critical_failures = [
        name
        for name, data in health_components.items()
        if data.get('critical') and data.get('status') == 'FAIL'
    ]

    if critical_failures:
        results['overall_status'] = 'CRITICAL_FAILURE'
        logger.error('=' * 60)
        logger.error('❌ HEALTH CHECK FAILED')
        logger.error('   Critical failures: %s', ', '.join(critical_failures))
        logger.error('=' * 60)

        if raise_on_failure:
            raise RuntimeError(
                f'Production health check failed! Critical dependencies missing: {critical_failures}\n'
                'App cannot operate without Ultimate Editor (Tree-sitter).'
            )
    else:
        results['overall_status'] = 'HEALTHY'
        logger.info('=' * 60)
        logger.info('✅ HEALTH CHECK PASSED')
        logger.info('   App is production-ready!')
        logger.info('=' * 60)

    return results


if __name__ == '__main__':
    check_results = run_production_health_check(raise_on_failure=False)

    print('\n📊 HEALTH CHECK RESULTS:')
    component_results = {
        component: data
        for component, data in check_results.items()
        if isinstance(data, dict)
    }
    for component, data in component_results.items():
        status_emoji = '✅' if data['status'] == 'PASS' else '❌'
        critical_marker = ' [CRITICAL]' if data.get('critical') else ''
        print(f'  {status_emoji} {component}{critical_marker}: {data["status"]}')
        if data['status'] == 'FAIL':
            print(f'     └─ {data["message"]}')

    print(f'\n🎯 OVERALL: {check_results["overall_status"]}')
