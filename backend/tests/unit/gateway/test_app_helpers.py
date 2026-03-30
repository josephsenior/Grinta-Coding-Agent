from backend.gateway.app import _get_optional_lifespan_timeout_sec


def test_get_optional_lifespan_timeout_sec_reads_app_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_OPTIONAL_LIFESPAN_TIMEOUT_SEC", "7.5")

    assert _get_optional_lifespan_timeout_sec() == 7.5