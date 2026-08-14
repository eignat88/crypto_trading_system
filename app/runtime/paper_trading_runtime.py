from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.models.market_event import MarketEvent


@dataclass(frozen=True)
class PaperRuntimeStatus:
    processed_events: int
    running: bool


class PaperTradingRuntime:
    """Coordinates paper market data and execution flow.

    This layer orchestrates runtime only. It does not contain strategy logic
    or risk rules.
    """

    def __init__(
        self,
        market_data: PaperMarketData,
        execution_engine: PaperExecutionEngine,
    ) -> None:
        self.market_data = market_data
        self.execution_engine = execution_engine
        self._processed_events = 0
        self._running = False

    @property
    def status(self) -> PaperRuntimeStatus:
        return PaperRuntimeStatus(
            processed_events=self._processed_events,
            running=self._running,
        )

    def run_once(self) -> bool:
        """Process the next available market event.

        Returns False when there is no new market data.
        """
        event: MarketEvent | None = next(
            self.market_data.stream(),
            None,
        )

        if event is None:
            return False

        self.execution_engine.on_market_event(event)
        self._processed_events += 1
        return True

    def run(self) -> Iterator[MarketEvent]:
        self._running = True

        try:
            for event in self.market_data.stream():
                self.execution_engine.on_market_event(event)
                self._processed_events += 1
                yield event
        finally:
            self._running = False
