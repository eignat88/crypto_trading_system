from pathlib import Path

import pytest

from scripts.migrate_database import discover_migrations


def test_discover_migrations_orders_versions(tmp_path: Path) -> None:
    (tmp_path / "022_last.sql").write_text("SELECT 22")
    (tmp_path / "001_first.sql").write_text("SELECT 1")

    assert [path.name for path in discover_migrations(tmp_path)] == [
        "001_first.sql",
        "022_last.sql",
    ]


def test_discover_migrations_rejects_duplicate_versions(tmp_path: Path) -> None:
    (tmp_path / "001_first.sql").touch()
    (tmp_path / "001_second.sql").touch()

    with pytest.raises(RuntimeError, match="Duplicate migration version 001"):
        discover_migrations(tmp_path)


def test_discover_migrations_rejects_noncanonical_sql_name(tmp_path: Path) -> None:
    (tmp_path / "paper.sql").touch()

    with pytest.raises(RuntimeError, match="Invalid migration filename"):
        discover_migrations(tmp_path)
