from datetime import datetime

from backend.gateway.routes.global_export import _build_export_filename


def test_build_export_filename_uses_app_prefix() -> None:
    timestamp = datetime(2025, 1, 6, 14, 30, 22)

    assert _build_export_filename(timestamp) == "app_backup_20250106_143022.json"