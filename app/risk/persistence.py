"""PostgreSQL persistence adapter for risk events and engine state."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, text


class PostgresRiskStateStore:
    """Persist risk state synchronously so a state change is durable before returning."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def load_state(self) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT state FROM risk_engine_state WHERE singleton_id = 1")
            ).scalar_one_or_none()
        return dict(row) if row is not None else None

    def save_state(self, state: dict[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO risk_engine_state (singleton_id, state, updated_at)
                    VALUES (1, CAST(:state AS jsonb), now())
                    ON CONFLICT (singleton_id) DO UPDATE
                    SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at"""
                ),
                {"state": json.dumps(state)},
            )

    def save_event(self, event: dict[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """INSERT INTO risk_events
                    (event_type, risk_level, symbol, side, quantity, price, reasons, occurred_at)
                    VALUES (:event_type, :risk_level, :symbol, :side, :quantity, :price,
                            CAST(:reasons AS jsonb), CAST(:occurred_at AS timestamptz))"""
                ),
                {**event, "reasons": json.dumps(event["reasons"])},
            )
