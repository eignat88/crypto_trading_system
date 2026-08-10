from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.connection import async_session_factory


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def _as_utc_datetime(value: datetime | str) -> datetime:
    """Normalize an ISO string or datetime to timezone-aware UTC."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
    else:
        raise TypeError(f"Expected datetime or ISO string, got {type(value).__name__}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def build_run_fingerprint(payload: dict[str, Any]) -> str:
    """Build a deterministic fingerprint from reproducibility inputs only."""
    metadata = payload["metadata"]
    reproducibility_inputs = {
        "git_commit": metadata.get("git_commit"),
        "exchange": metadata["exchange"],
        "symbol": metadata["symbol"],
        "interval": metadata["interval"],
        "start": metadata["start"],
        "end": metadata["end"],
        "candle_count": metadata["candle_count"],
        "random_seed": metadata["random_seed"],
        "strategy": payload["strategy"],
        "configuration": payload["configuration"],
    }
    return hashlib.sha256(_json_dumps(reproducibility_inputs).encode("utf-8")).hexdigest()


def run_id_from_fingerprint(fingerprint: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"crypto_trading_system/backtest/{fingerprint}")


async def persist_backtest_audit(
    payload: dict[str, Any],
    audit_file: str | None,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> UUID:
    """Persist a complete backtest audit in one transaction.

    Re-running the exact same reproducibility inputs produces the same run_id.
    Child rows use (run_id, sequence_no) keys and ON CONFLICT DO NOTHING, making
    persistence safe to retry after a process-level retry.
    """
    fingerprint = build_run_fingerprint(payload)
    run_id = run_id_from_fingerprint(fingerprint)
    metadata = payload["metadata"]
    strategy = payload["strategy"]
    backtest = payload["backtest"]
    audit = payload["audit"]

    run_statement = text(
        """
        INSERT INTO mart.backtest_run (
            run_id, run_fingerprint, created_at, git_commit,
            exchange_name, symbol, interval_code, period_start, period_end,
            candle_count, random_seed, strategy_name, parameters_version,
            strategy_parameters, backtest_config, initial_balance, final_equity,
            total_pnl, total_trades, winning_trades, losing_trades, win_rate,
            profit_factor, average_trade, average_win, average_loss,
            max_drawdown, max_consecutive_losses, audit_file
        ) VALUES (
            :run_id, :run_fingerprint, :created_at, :git_commit,
            :exchange_name, :symbol, :interval_code, :period_start, :period_end,
            :candle_count, :random_seed, :strategy_name, :parameters_version,
            CAST(:strategy_parameters AS jsonb), CAST(:backtest_config AS jsonb),
            :initial_balance, :final_equity, :total_pnl, :total_trades,
            :winning_trades, :losing_trades, :win_rate, :profit_factor,
            :average_trade, :average_win, :average_loss, :max_drawdown,
            :max_consecutive_losses, :audit_file
        )
        ON CONFLICT (run_fingerprint) DO UPDATE
        SET audit_file = COALESCE(EXCLUDED.audit_file, mart.backtest_run.audit_file)
        """
    )

    signal_statement = text(
        """
        INSERT INTO mart.backtest_signal (
            run_id, sequence_no, action, symbol, signal_time, strategy_name,
            parameters_version, regime, reason, payload
        ) VALUES (
            :run_id, :sequence_no, :action, :symbol, :signal_time, :strategy_name,
            :parameters_version, :regime, :reason, CAST(:payload AS jsonb)
        )
        ON CONFLICT (run_id, sequence_no) DO NOTHING
        """
    )

    risk_statement = text(
        """
        INSERT INTO mart.backtest_risk_decision (
            run_id, sequence_no, order_id, approved, risk_level, payload
        ) VALUES (
            :run_id, :sequence_no, :order_id, :approved, :risk_level,
            CAST(:payload AS jsonb)
        )
        ON CONFLICT (run_id, sequence_no) DO NOTHING
        """
    )

    order_statement = text(
        """
        INSERT INTO mart.backtest_order (
            run_id, sequence_no, order_id, symbol, side, created_at, payload
        ) VALUES (
            :run_id, :sequence_no, :order_id, :symbol, :side, :created_at,
            CAST(:payload AS jsonb)
        )
        ON CONFLICT (run_id, sequence_no) DO NOTHING
        """
    )

    fill_statement = text(
        """
        INSERT INTO mart.backtest_fill (
            run_id, sequence_no, fill_id, order_id, symbol, side,
            quantity, price, commission, fill_time, payload
        ) VALUES (
            :run_id, :sequence_no, :fill_id, :order_id, :symbol, :side,
            :quantity, :price, :commission, :fill_time, CAST(:payload AS jsonb)
        )
        ON CONFLICT (run_id, sequence_no) DO NOTHING
        """
    )

    signal_rows = [
        {
            "run_id": run_id,
            "sequence_no": index,
            "action": item["action"],
            "symbol": item["symbol"],
            "signal_time": _as_utc_datetime(item["timestamp"]),
            "strategy_name": item.get("strategy", ""),
            "parameters_version": item.get("parameters_version", ""),
            "regime": item.get("regime"),
            "reason": item.get("reason", ""),
            "payload": _json_dumps(item),
        }
        for index, item in enumerate(audit["signals"], start=1)
    ]

    risk_rows = [
        {
            "run_id": run_id,
            "sequence_no": index,
            "order_id": item["order_id"],
            "approved": item["approved"],
            "risk_level": item["risk_level"],
            "payload": _json_dumps(item),
        }
        for index, item in enumerate(audit["risk_decisions"], start=1)
    ]

    order_rows = [
        {
            "run_id": run_id,
            "sequence_no": index,
            "order_id": item["order_id"],
            "symbol": item["signal"]["symbol"],
            "side": item["side"],
            "created_at": _as_utc_datetime(item["created_at"]),
            "payload": _json_dumps(item),
        }
        for index, item in enumerate(audit["orders"], start=1)
    ]

    fill_rows = [
        {
            "run_id": run_id,
            "sequence_no": index,
            "fill_id": item["fill_id"],
            "order_id": item["order_id"],
            "symbol": item["symbol"],
            "side": item["side"],
            "quantity": item["quantity"],
            "price": item["price"],
            "commission": item["commission"],
            "fill_time": _as_utc_datetime(item["timestamp"]),
            "payload": _json_dumps(item),
        }
        for index, item in enumerate(audit["fills"], start=1)
    ]

    run_values = {
        "run_id": run_id,
        "run_fingerprint": fingerprint,
        "created_at": _as_utc_datetime(metadata["created_at"]),
        "git_commit": metadata.get("git_commit"),
        "exchange_name": metadata["exchange"],
        "symbol": metadata["symbol"],
        "interval_code": metadata["interval"],
        "period_start": _as_utc_datetime(metadata["start"]),
        "period_end": _as_utc_datetime(metadata["end"]),
        "candle_count": metadata["candle_count"],
        "random_seed": metadata["random_seed"],
        "strategy_name": strategy["name"],
        "parameters_version": strategy["parameters"]["parameters_version"],
        "strategy_parameters": _json_dumps(strategy["parameters"]),
        "backtest_config": _json_dumps(payload["configuration"]),
        "initial_balance": backtest["initial_balance"],
        "final_equity": backtest["final_equity"],
        "total_pnl": backtest["total_pnl"],
        "total_trades": backtest["total_trades"],
        "winning_trades": backtest["winning_trades"],
        "losing_trades": backtest["losing_trades"],
        "win_rate": backtest["win_rate"],
        "profit_factor": backtest["profit_factor"],
        "average_trade": backtest["average_trade"],
        "average_win": backtest["average_win"],
        "average_loss": backtest["average_loss"],
        "max_drawdown": backtest["max_drawdown"],
        "max_consecutive_losses": backtest["max_consecutive_losses"],
        "audit_file": audit_file,
    }

    async with session_factory() as session:
        async with session.begin():
            await session.execute(run_statement, run_values)
            if signal_rows:
                await session.execute(signal_statement, signal_rows)
            if risk_rows:
                await session.execute(risk_statement, risk_rows)
            if order_rows:
                await session.execute(order_statement, order_rows)
            if fill_rows:
                await session.execute(fill_statement, fill_rows)

    return run_id
