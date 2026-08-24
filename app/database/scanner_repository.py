"""Scanner repository for persisting and querying signals."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.scanner.models import ScannerResult


class ScannerRepository:
    """Repository for scanner signal persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_signal(self, result: ScannerResult) -> int | None:
        query = text("""
            INSERT INTO scanner_signals (
                symbol, timeframe, setup_type, direction, score,
                detected_at, candle_time, price, breakout_level,
                atr, ema20, ema50, ema200, volume_ma20,
                scanner_version, parameters_version, metadata
            ) VALUES (
                :symbol, :timeframe, :setup_type, :direction, :score,
                :detected_at, :candle_time, :price, :breakout_level,
                :atr, :ema20, :ema50, :ema200, :volume_ma20,
                :scanner_version, :parameters_version, :metadata::jsonb
            )
            ON CONFLICT (symbol, setup_type, candle_time, breakout_level) DO NOTHING
            RETURNING id
        """)
        result_row = await self.session.execute(query, {
            "symbol": result.symbol,
            "timeframe": result.timeframe,
            "setup_type": result.setup_type.value,
            "direction": result.direction.value,
            "score": float(result.score),
            "detected_at": result.detected_at,
            "candle_time": result.candle_timestamp,
            "price": float(result.current_price),
            "breakout_level": float(result.breakout_level) if result.breakout_level else None,
            "atr": float(result.atr) if result.atr else None,
            "ema20": float(result.ema20) if result.ema20 else None,
            "ema50": float(result.ema50) if result.ema50 else None,
            "ema200": float(result.ema200) if result.ema200 else None,
            "volume_ma20": float(result.volume_ma20) if result.volume_ma20 else None,
            "scanner_version": result.scanner_version,
            "parameters_version": result.parameters_version,
            "metadata": str(result.metadata) if result.metadata else "{}",
        })
        row = result_row.fetchone()
        return row[0] if row else None

    async def save_signals(self, results: list[ScannerResult]) -> int:
        count = 0
        for result in results:
            if await self.save_signal(result) is not None:
                count += 1
        return count

    async def get_recent_signals(self, symbol: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        conditions = []
        params: dict[str, Any] = {"limit": limit}
        if symbol:
            conditions.append("symbol = :symbol")
            params["symbol"] = symbol
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        query = text(f"SELECT * FROM scanner_signals {where} ORDER BY detected_at DESC LIMIT :limit")
        result = await self.session.execute(query, params)
        return [dict(row) for row in result.fetchall()]
