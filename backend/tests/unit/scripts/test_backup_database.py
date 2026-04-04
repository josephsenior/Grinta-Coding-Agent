from datetime import datetime

from backend.scripts.database.backup_database import build_backup_filename


def test_build_backup_filename_uses_app_prefix_for_sql() -> None:
    timestamp = datetime(2025, 1, 6, 14, 30, 22)

    assert build_backup_filename(timestamp) == 'app_backup_20250106_143022.sql'


def test_build_backup_filename_supports_custom_suffix() -> None:
    timestamp = datetime(2025, 1, 6, 14, 30, 22)

    assert (
        build_backup_filename(timestamp, '.dump') == 'app_backup_20250106_143022.dump'
    )
