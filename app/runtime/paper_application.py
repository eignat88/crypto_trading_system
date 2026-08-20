from __future__ import annotations

import asyncio
import signal

import structlog

from app.runtime.dependencies import PaperDependencies
from app.runtime.lifecycle import RuntimeLifecycle, RuntimeState
from app.runtime.preflight import StartupPreflight


class PaperApplication:
    """Own startup, recovery, warmup, event-loop and durable shutdown."""

    def __init__(self, dependencies: PaperDependencies) -> None:
        self.dependencies = dependencies
        self.lifecycle = RuntimeLifecycle()
        self.trading_enabled = False
        self._run_task: asyncio.Task[None] | None = None
        self._stop_lock = asyncio.Lock()
        self._logger = structlog.get_logger()

    async def start(self) -> None:
        if self.lifecycle.state is not RuntimeState.CREATED:
            raise RuntimeError("Paper application can only be started once")
        self.lifecycle.transition(RuntimeState.PREFLIGHT)
        preflight = StartupPreflight(
            trading_mode=self.dependencies.trading_mode,
            exchange=self.dependencies.exchange,
            symbols=self.dependencies.symbols,
            initial_capital=self.dependencies.initial_capital,
            risk_config=self.dependencies.risk_config,
            database_check=self.dependencies.database_check,
            migration_check=self.dependencies.migration_check,
            repository=self.dependencies.repository,
        )
        result = await preflight.run()
        self._logger.info("preflight_completed", success=result.success, checks=result.checks)
        if not result.success:
            self.lifecycle.transition(RuntimeState.STOPPING)
            self.trading_enabled = False
            await self.dependencies.close()
            self.lifecycle.transition(RuntimeState.STOPPED)
            raise RuntimeError("Paper runtime preflight failed: " + "; ".join(result.errors))

        self.lifecycle.transition(RuntimeState.RESTORING)
        restored = await self.dependencies.runtime.restore_state()
        self._logger.info(
            "state_restored",
            restored=restored is not None,
            last_sequence=restored.last_market_sequence if restored else 0,
        )
        self._logger.info("risk_engine_initialized")

        self.lifecycle.transition(RuntimeState.WARMUP)
        available = await self.dependencies.warmup(
            self.dependencies.symbols, self.dependencies.warmup_candles
        )
        insufficient = {
            symbol: count
            for symbol, count in available.items()
            if count < self.dependencies.warmup_candles
        }
        missing = set(self.dependencies.symbols) - set(available)
        insufficient.update({symbol: 0 for symbol in missing})
        self.trading_enabled = not insufficient
        self.dependencies.runtime.trading_enabled = self.trading_enabled
        self._logger.info(
            "market_warmup_completed",
            trading_enabled=self.trading_enabled,
            required=self.dependencies.warmup_candles,
            insufficient=insufficient,
        )
        self.lifecycle.transition(RuntimeState.RUNNING)
        self._run_task = asyncio.create_task(
            self.dependencies.runtime.run_async(restore_on_start=False),
            name="paper-trading-runtime",
        )
        self._logger.info("paper_runtime_started", trading_enabled=self.trading_enabled)

    async def stop(self) -> None:
        async with self._stop_lock:
            if self.lifecycle.state is RuntimeState.STOPPED:
                return
            if self.lifecycle.state is not RuntimeState.STOPPING:
                self.lifecycle.transition(RuntimeState.STOPPING)
            self.trading_enabled = False
            self.dependencies.runtime.trading_enabled = False
            self.dependencies.runtime.stop()
            if self._run_task is not None:
                await self._run_task
            else:
                await self.dependencies.runtime.checkpoint()
            if self.dependencies.pnl_checkpoint is not None:
                await self.dependencies.pnl_checkpoint()
            await self.dependencies.close()
            self.lifecycle.transition(RuntimeState.STOPPED)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        stop_requested = asyncio.Event()
        installed: list[signal.Signals] = []
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, stop_requested.set)
                installed.append(signum)
            except NotImplementedError:  # pragma: no cover - Windows event loop
                pass
        try:
            await self.start()
            assert self._run_task is not None
            signal_task = asyncio.create_task(stop_requested.wait())
            done, _ = await asyncio.wait(
                {self._run_task, signal_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if self._run_task in done:
                await self._run_task
            signal_task.cancel()
        finally:
            await self.stop()
            for signum in installed:
                loop.remove_signal_handler(signum)
