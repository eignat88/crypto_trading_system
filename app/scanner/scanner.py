"""Main scanner engine — orchestrates detectors and produces ranked results."""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.scanner.models import ScannerResult
from app.scanner.scoring import ScoringWeights, calculate_score, rank_signals
from app.scanner.universe import UniverseConfig
from app.setups.base import (
    BaseSetupDetector,
    CandleData,
    IndicatorSnapshot,
)
from app.setups.breakout import BreakoutDetector
from app.setups.breakout_retest import RetestReadyDetector
from app.setups.compression import CompressionDetector
from app.setups.failed_breakout import FailedBreakoutDetector

logger = structlog.get_logger()


class ScannerEngine:
    """Main scanner engine that runs all detectors and produces ranked results."""

    def __init__(
        self,
        universe: UniverseConfig | None = None,
        weights: ScoringWeights | None = None,
        detectors: list[BaseSetupDetector] | None = None,
    ) -> None:
        self.universe = universe or UniverseConfig()
        self.weights = weights or ScoringWeights()
        self.detectors = detectors or [
            BreakoutDetector(),
            RetestReadyDetector(),
            FailedBreakoutDetector(),
            CompressionDetector(),
        ]
        self._state: dict[str, dict[str, Any]] = {}

    def get_state(self, symbol: str) -> dict[str, Any]:
        if symbol not in self._state:
            self._state[symbol] = {}
        return self._state[symbol]

    def scan(
        self,
        candle_data: dict[str, list[CandleData]],
        indicators: dict[str, IndicatorSnapshot],
        btc_regime: str | None = None,
    ) -> list[ScannerResult]:
        start_time = time.time()
        all_signals = []
        scanned = 0

        for symbol in self.universe.symbols:
            candles = candle_data.get(symbol, [])
            if len(candles) < self.universe.min_candles:
                continue

            symbol_indicators = indicators.get(symbol, IndicatorSnapshot())
            state = self.get_state(symbol)
            scanned += 1

            for detector in self.detectors:
                try:
                    signal = detector.detect(
                        symbol=symbol,
                        timeframe=self.universe.timeframe,
                        candles=candles,
                        indicators=symbol_indicators,
                        state=state,
                    )
                    if signal is not None:
                        score = calculate_score(
                            signal=signal,
                            indicators={
                                "ema50": symbol_indicators.ema50,
                                "ema200": symbol_indicators.ema200,
                                "volume_ma20": symbol_indicators.volume_ma20,
                            },
                            btc_regime=btc_regime,
                            weights=self.weights,
                        )
                        signal.score = score
                        all_signals.append(signal)
                except Exception as e:
                    logger.error("detector_error", symbol=symbol, error=str(e))

        ranked = rank_signals(all_signals)

        results = []
        seen_ids: set[str] = set()
        for signal in ranked:
            signal_id = f"{signal.symbol}|{signal.setup_type.value}"
            if signal_id in seen_ids:
                continue
            seen_ids.add(signal_id)

            ind = indicators.get(signal.symbol, IndicatorSnapshot())
            result = ScannerResult(
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                setup_type=signal.setup_type,
                direction=signal.direction,
                score=signal.score,
                detected_at=signal.detected_at,
                current_price=signal.current_price,
                ema20=ind.ema20,
                ema50=ind.ema50,
                ema200=ind.ema200,
                atr=ind.atr,
                volume_ma20=ind.volume_ma20,
                metadata=signal.metadata,
                candle_timestamp=signal.candle_timestamp,
            )
            results.append(result)

        duration = time.time() - start_time
        logger.info("scan_complete", scanned=scanned, signals=len(results), duration=f"{duration:.1f}s")
        return results
