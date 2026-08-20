#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys

import structlog

from app.config.settings import Settings
from app.runtime.dependencies import build_paper_dependencies
from app.runtime.paper_application import PaperApplication


async def main() -> None:
    # Check the raw value before pydantic parses it so unknown modes fail closed
    # with the same controlled startup error as an explicitly forbidden live mode.
    mode = os.getenv("TRADING_MODE", "paper").lower()
    if mode != "paper":
        raise RuntimeError(f"Paper runtime refuses TRADING_MODE={mode}")
    dependencies = await build_paper_dependencies(Settings())
    await PaperApplication(dependencies).run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, RuntimeError, OSError) as exc:
        structlog.get_logger().critical("paper_runtime_startup_failed", error=str(exc))
        sys.exit(1)
