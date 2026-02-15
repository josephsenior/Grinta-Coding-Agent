"""Pytest configuration for E2E tests."""


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: mark test as end-to-end integration test")
    config.addinivalue_line("markers", "playwright: mark test as requiring Playwright")
    config.addinivalue_line(
        "markers", "chrome_devtools: mark test as using Chrome DevTools"
    )
    config.addinivalue_line("markers", "integration: mark test as integration test")
