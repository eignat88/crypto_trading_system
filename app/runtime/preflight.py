from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


class RestoreRepository(Protocol):
    async def load_state(self) -> object | None: ...


@dataclass(frozen=True)
class PreflightResult:
    success: bool
    checks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class StartupPreflight:
    """Run all startup gates without short-circuiting their diagnostics."""

    def __init__(
        self,
        *,
        trading_mode: str,
        exchange: str,
        symbols: list[str],
        initial_capital: Decimal,
        risk_config: object | None,
        database_check: Callable[[], Awaitable[bool]],
        migration_check: Callable[[], Awaitable[bool]],
        repository: RestoreRepository | None,
    ) -> None:
        self.trading_mode = trading_mode
        self.exchange = exchange
        self.symbols = symbols
        self.initial_capital = initial_capital
        self.risk_config = risk_config
        self.database_check = database_check
        self.migration_check = migration_check
        self.repository = repository

    async def run(self) -> PreflightResult:
        checks: list[str] = []
        errors: list[str] = []
        if self.trading_mode == "paper":
            checks.append("trading_mode=paper")
        elif self.trading_mode == "live":
            errors.append("Live mode cannot start the paper runtime")
        else:
            errors.append(f"Unknown trading mode: {self.trading_mode}")

        if self.exchange.strip():
            checks.append("exchange_configuration")
        else:
            errors.append("Exchange configuration is missing")
        if self.symbols and all(symbol.strip() for symbol in self.symbols):
            checks.append("symbol_list")
        else:
            errors.append("Symbol list is missing")
        if self.initial_capital > 0:
            checks.append("initial_capital")
        else:
            errors.append("Initial capital must be positive")
        if self.risk_config is not None:
            checks.append("risk_configuration")
        else:
            errors.append("Risk configuration is missing")

        try:
            database_ok = await self.database_check()
        except Exception:
            database_ok = False
        if database_ok:
            checks.append("database_connection")
        else:
            errors.append("Database unavailable")

        try:
            migrations_ok = database_ok and await self.migration_check()
        except Exception:
            migrations_ok = False
        if migrations_ok:
            checks.append("migration_state")
        else:
            errors.append("Database migration state is unavailable")

        if self.repository is None:
            errors.append("Paper state repository is unavailable")
        else:
            try:
                await self.repository.load_state()
                checks.append("restore_available")
            except Exception:
                errors.append("Paper state restore is unavailable")
        return PreflightResult(not errors, checks, errors)
