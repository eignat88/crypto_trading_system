"""Canonical, checksum-protected PostgreSQL migration runner."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Connection, create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "database" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(?P<version>\d{3})_[a-z0-9_]+\.sql$")
_LOCK_ID = 1_664_902_783


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> tuple[Path, ...]:
    """Return canonical migrations in version order, rejecting ambiguous names."""
    migrations: list[tuple[int, Path]] = []
    versions: dict[int, Path] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix != ".sql":
            continue
        match = MIGRATION_PATTERN.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"Invalid migration filename: {path.name}")
        version = int(match.group("version"))
        if previous := versions.get(version):
            raise RuntimeError(
                f"Duplicate migration version {version:03d}: {previous.name}, {path.name}"
            )
        versions[version] = path
        migrations.append((version, path))
    if not migrations:
        raise RuntimeError(f"No migrations found in {directory}")
    return tuple(path for _, path in sorted(migrations))


def _checksum(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _ensure_history(connection: Connection) -> None:
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def apply_migrations(database_url: str, directory: Path = MIGRATIONS_DIR) -> None:
    """Apply pending migrations atomically and validate recorded checksums."""
    migrations = discover_migrations(directory)
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                _ensure_history(connection)
                connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": _LOCK_ID})

            for migration in migrations:
                version = int(migration.name[:3])
                contents = migration.read_bytes()
                checksum = _checksum(contents)
                with connection.begin():
                    recorded = connection.execute(
                        text(
                            "SELECT filename, checksum FROM public.schema_migrations "
                            "WHERE version = :version"
                        ),
                        {"version": version},
                    ).one_or_none()
                    if recorded:
                        history_changed = (
                            recorded.filename != migration.name
                            or recorded.checksum.strip() != checksum
                        )
                        if history_changed:
                            raise RuntimeError(
                                f"Migration {version:03d} differs from recorded history"
                            )
                        print(f"skipped={migration.name}")
                        continue

                    print(f"applying={migration.name}")
                    connection.exec_driver_sql(contents.decode("utf-8-sig"))
                    connection.execute(
                        text(
                            "INSERT INTO public.schema_migrations(version, filename, checksum) "
                            "VALUES (:version, :filename, :checksum)"
                        ),
                        {"version": version, "filename": migration.name, "checksum": checksum},
                    )
                    print(f"applied={migration.name}")
    finally:
        engine.dispose()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply all canonical PostgreSQL migrations")
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy sync URL; defaults to the project's PostgreSQL configuration",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        apply_migrations(args.database_url or settings.database_url_sync)
    except Exception as error:
        print(f"migration_status=failed error={error}", file=sys.stderr)
        return 1
    print("migration_status=success")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
