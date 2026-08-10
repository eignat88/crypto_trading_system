from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.backtest.walk_forward import WalkForwardConfig, generate_walk_forward_windows, run_fixed_parameter_walk_forward
from app.reporting.breakout_retest_attribution import reconstruct_breakout_retest_trades
from app.reporting.breakout_retest_early_failure_counterfactual import build_early_failure_counterfactual
from app.strategies.breakout_retest import BreakoutRetestStrategy
from scripts.run_backtest import load_candles, parse_datetime

EXPECTED={"BTCUSDT":(Decimal("-0.1391016840064235879634907285"),49),"ETHUSDT":(Decimal("-3.153621560329388837431488648"),64)}
TOL=Decimal("1E-24")

def _jd(v:Any)->str:
    if isinstance(v,Decimal): return str(v)
    if isinstance(v,datetime): return v.astimezone(timezone.utc).isoformat()
    return str(v)

async def main()->None:
    p=argparse.ArgumentParser(description="Read-only 24h early-failure counterfactual for Breakout Retest v1")
    p.add_argument("--symbols",nargs="+",default=["BTCUSDT","ETHUSDT"],choices=["BTCUSDT","ETHUSDT"])
    p.add_argument("--exchange",default="bybit"); p.add_argument("--interval",default="1h")
    p.add_argument("--start",required=True); p.add_argument("--end",required=True)
    p.add_argument("--train-days",type=int,default=180); p.add_argument("--test-days",type=int,default=60); p.add_argument("--step-days",type=int,default=60)
    p.add_argument("--initial-balance",type=Decimal,default=Decimal("500")); p.add_argument("--seed",type=int,default=42)
    a=p.parse_args()
    if a.interval!="1h": raise ValueError("Frozen counterfactual supports only 1h")
    start,end=parse_datetime(a.start),parse_datetime(a.end)
    cfg=WalkForwardConfig(train_days=a.train_days,test_days=a.test_days,step_days=a.step_days,initial_balance=a.initial_balance,random_seed=a.seed)
    windows=generate_walk_forward_windows(start,end,cfg)
    payload=[]; actual_total=Decimal("0"); cf_total=Decimal("0"); triggered=0; sacrificed=0; saved=0
    for symbol in a.symbols:
        candles=await load_candles(a.exchange,symbol,a.interval,start,end)
        agg=run_fixed_parameter_walk_forward(candles=candles,symbol=symbol,interval=a.interval,start=start,end=end,config=cfg,strategy_factory=lambda s:BreakoutRetestStrategy([s]))
        exp_pnl,exp_trades=EXPECTED[symbol]
        if abs(agg.total_oos_pnl-exp_pnl)>TOL or agg.total_oos_trades!=exp_trades: raise ValueError(f"Frozen reproduction failed for {symbol}")
        trades=[]; by_window={}
        for w in windows:
            tc=[c for c in candles if w.test_start<=c["open_time"]<w.test_end]; by_window[w.index]=tc
            r=BacktestEngine(BacktestConfig(initial_balance=cfg.initial_balance,random_seed=cfg.random_seed)).run(candles=tc,strategy=BreakoutRetestStrategy([symbol]),indicator_provider=lambda c,i:c["indicators"])
            trades.extend(reconstruct_breakout_retest_trades(r,symbol=symbol,window_index=w.index))
        s=build_early_failure_counterfactual(tuple(trades),candles_by_window=by_window,symbol=symbol,base_seed=a.seed)
        print(f"\nEARLY FAILURE COUNTERFACTUAL: {symbol}\n"+"="*(30+len(symbol)))
        print(f"trades               : {s.trades}\ntriggered             : {s.triggered}\nactual_pnl            : {s.actual_pnl}\ncounterfactual_pnl    : {s.counterfactual_pnl}\npnl_delta             : {s.pnl_delta}\nactual_winners        : {s.actual_winners}\ncounterfactual_winners: {s.counterfactual_winners}\nsacrificed_winners    : {s.sacrificed_winners}\nsaved_losers          : {s.saved_losers}")
        print("WINDOWS")
        for w in s.by_window: print(f"w{w['window_index']:02d} trig={w['triggered']} actual={w['actual_pnl']} cf={w['counterfactual_pnl']} delta={w['pnl_delta']} sacrificed={w['sacrificed_winners']} saved={w['saved_losers']}")
        payload.append(asdict(s)); actual_total+=s.actual_pnl; cf_total+=s.counterfactual_pnl; triggered+=s.triggered; sacrificed+=s.sacrificed_winners; saved+=s.saved_losers
    print("\nCOMBINED EARLY FAILURE COUNTERFACTUAL\n=====================================")
    print(f"actual_pnl         : {actual_total}\ncounterfactual_pnl : {cf_total}\npnl_delta          : {cf_total-actual_total}\ntriggered          : {triggered}\nsacrificed_winners : {sacrificed}\nsaved_losers       : {saved}")
    out=Path("artifacts/diagnostics"); out.mkdir(parents=True,exist_ok=True); ts=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path=out/f"breakout_retest_early_failure_counterfactual_{ts}.json"; path.write_text(json.dumps({"metadata":{"rule":"24h close < entry; execute N+1 open","seed":a.seed},"actual_pnl":actual_total,"counterfactual_pnl":cf_total,"pnl_delta":cf_total-actual_total,"symbols":payload},indent=2,default=_jd),encoding="utf-8")
    print(f"artifact           : {path}")

if __name__=="__main__": asyncio.run(main())
