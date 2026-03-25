"""Tests for backend.api.route_dependencies module with auth disabled."""


class TestGetDependencies:
    def test_returns_empty_list_when_auth_disabled(self):
        from backend.api.route_dependencies import get_dependencies

        deps = get_dependencies()
        assert isinstance(deps, list)
        assert deps == []

