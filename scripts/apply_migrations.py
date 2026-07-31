"""Apply the ordered PostgreSQL migrations used by the project."""

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(
    PROJECT_ROOT / "sql" / f"{number:03d}_{name}.sql"
    for number, name in (
        (1, "create_raw"),
        (2, "create_dds"),
        (3, "create_mart"),
        (4, "add_api_request_id"),
        (5, "raw_to_dds_etl"),
        (6, "create_risk_state"),
    )
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL migrations 001-006")
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy sync URL; defaults to DATABASE_URL_SYNC from the environment",
    )
    return parser.parse_args()


def apply_migrations(database_url: str) -> None:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        for migration in MIGRATIONS:
            sql = migration.read_text(encoding="utf-8-sig")
            with engine.begin() as connection:
                connection.exec_driver_sql(sql)
            print(f"applied={migration.name}")

        with engine.connect() as connection:
            function_exists = connection.execute(
                text(
                    """
                    SELECT to_regprocedure(
                        'dds.load_raw_candles(text,text,text,timestamptz)'
                    ) IS NOT NULL
                    """
                )
            ).scalar_one()
        if not function_exists:
            raise RuntimeError("dds.load_raw_candles() was not created")
    finally:
        engine.dispose()


def main() -> None:
    args = parse_args()
    apply_migrations(args.database_url or settings.database_url_sync)
    print("migration_status=success")


if __name__ == "__main__":
    main()
