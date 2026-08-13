# CTS MVP v2.3.1 TradingView Numeric Parity Fixtures

## Source

TradingView Pine Script:

Crypto Trading System MVP v2.3.1

## Purpose

These fixtures are used to validate Python CTS implementation against TradingView exported reference values.

## Symbols

- BTCUSDT
- ETHUSDT

## Timeframe

- 1H

## Expected fields

Indicators:

- TV_EMA20
- TV_EMA50
- TV_EMA200
- TV_RSI14
- TV_ATR14

Confirmed HTF values:

- TV_HTF_EMA20
- TV_HTF_EMA50
- TV_HTF_EMA200
- TV_HTF_RSI14

Strategy state:

- TV_PULLBACK_STATE
- TV_COOLDOWN_READY
- TV_DCA_SIGNAL

Reference CSV files must not be modified manually. A new TradingView export is required for any fixture change.
