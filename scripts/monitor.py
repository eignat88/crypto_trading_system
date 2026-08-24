#!/usr/bin/env python3
"""Monitor paper trading system status."""

import sys
import time
from datetime import datetime, UTC

import psycopg


DB_URL = "postgresql://postgres:123@localhost:5432/crypto_trading"


def get_status():
    conn = psycopg.connect(DB_URL)
    cur = conn.cursor()
    status = {}

    # Positions
    cur.execute("SELECT symbol, quantity, average_price FROM public.paper_positions WHERE quantity > 0")
    status["positions"] = cur.fetchall()

    # Recent fills
    cur.execute("SELECT symbol, quantity, price, commission, executed_at FROM public.paper_fills ORDER BY executed_at DESC LIMIT 5")
    status["recent_fills"] = cur.fetchall()

    # Cash balance
    cur.execute("SELECT balance FROM public.paper_balances WHERE asset = 'USDT' ORDER BY updated_at DESC LIMIT 1")
    row = cur.fetchone()
    status["cash"] = float(row[0]) if row else 0

    # Heartbeat
    cur.execute("SELECT status, last_cycle_time FROM monitoring.runtime_health WHERE runtime_id = 'paper-runtime-001'")
    status["heartbeat"] = cur.fetchone()

    conn.close()
    return status


def format_status(status):
    lines = []
    lines.append("=" * 60)
    lines.append("  PAPER TRADING MONITOR")
    lines.append(f"  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("=" * 60)

    hb = status.get("heartbeat")
    if hb:
        state, last_beat = hb
        age = (datetime.now(UTC) - last_beat).total_seconds() / 60 if last_beat else 999
        icon = "OK" if state == "RUNNING" and age < 5 else "WARN"
        lines.append(f"  System: {icon} ({state}, last beat: {age:.0f}m ago)")
    else:
        lines.append("  System: UNKNOWN")

    lines.append(f"  Cash: ${status['cash']:,.2f}")

    positions = status.get("positions", [])
    if positions:
        lines.append(f"\n  Open Positions ({len(positions)}):")
        for p in positions:
            symbol, qty, avg_price = p
            lines.append(f"    {symbol}: {qty} @ ${float(avg_price):,.2f}")
    else:
        lines.append("\n  No open positions")

    fills = status.get("recent_fills", [])
    if fills:
        lines.append(f"\n  Recent Fills ({len(fills)}):")
        for f in fills:
            symbol, qty, price, commission, ts = f
            lines.append(f"    {ts.strftime('%m-%d %H:%M')} {qty} {symbol} @ ${float(price):,.2f} (fee: ${float(commission or 0):,.4f})")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    once = "--once" in sys.argv
    if once:
        print(format_status(get_status()))
        return

    print("Monitoring (Ctrl+C to stop)...\n")
    while True:
        try:
            print("\033[2J\033[H")
            print(format_status(get_status()))
            time.sleep(30)
        except KeyboardInterrupt:
            print("\nStopped")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
