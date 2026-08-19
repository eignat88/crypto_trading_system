"""Backward-compatible entry point for the canonical migration runner."""

from migrate_database import apply_migrations, main

__all__ = ["apply_migrations", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
