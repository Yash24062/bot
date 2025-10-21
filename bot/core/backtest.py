from __future__ import annotations
import os
import time
import importlib
from datetime import datetime, timezone
from colorama import Fore, Style
import numpy as np
import pandas as pd

from bot.utils.paths import ensure_dir
from bot.utils.metrics import (
    compute_sharpe_ratio,
    compute_max_drawdown,
    compute_streak_stats,
)
from bot.utils.trades import summarize_trades


class TFBacktest:
    def __init__(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        start_balance: float = 25.0,
        position_pct: float = 0.05,
        leverage: float = 10.0,
        debug: bool = False,
    ):
        self.symbol = symbol
        self.timeframe = timeframe
        self.df = df
        self.starting_balance = start_balance
        self.position_pct = position_pct
        self.leverage = leverage
        self.debug = debug
        self.trades = []
        self.balance = start_balance

        # 🧠 Auto-load correct logic file based on timeframe
        self.logic = self.load_logic_by_timeframe(timeframe)

    # ----------------- LOGIC LOADER -----------------
    @staticmethod
    def load_logic_by_timeframe(tf: str):
        """Auto-import the right trading logic module based on timeframe."""
        tf = tf.lower()

        mapping = {
            "1m": "logic_1m",
            "5m": "logic_5m",
            "15m": "logic_15m",
            "1h": "logic_1h",
            "4h": "logic_4h",
            "1d": "logic_1d",
        }

        logic_name = None
        for key, val in mapping.items():
            if key in tf:
                logic_name = val
                break
        if logic_name is None:
            print(f"{Fore.YELLOW}⚠️ Unknown timeframe '{tf}' → defaulting to logic_1m{Style.RESET_ALL}")
            logic_name = "logic_1m"

        try:
            module = importlib.import_module(f"bot.trading.{logic_name}")
            print(f"{Fore.YELLOW}Loaded trading logic: {logic_name}{Style.RESET_ALL}")
            return module
        except ModuleNotFoundError:
            print(f"{Fore.RED}⚠️ Could not find bot.trading.{logic_name} → using bot.trading.logic_1m fallback.{Style.RESET_ALL}")
            return importlib.import_module("bot.trading.logic_1m")

    # ------------------------------------------------

    def log(self, msg):
        if self.debug:
            print(f"{Fore.CYAN}{msg}{Style.RESET_ALL}")

    def run(self):
        self.log(f"Running backtest for {self.symbol} {self.timeframe} ...")
        self.trades = []
        start_time = time.time()

        df = self.df.copy().reset_index(drop=True)
        logic = self.logic
        entry_state = None
        entry_idx = entry_price = entry_atr = None
        entry_reason = side = None

        # --- Pre-calc ATR if strategy requires it
        if "atr" not in df.columns and hasattr(logic, "calculate_atr"):
            df["atr"] = logic.calculate_atr(df)

        for i in range(len(df)):
            price = df["close"].iloc[i]

            # --- Entry logic
            if entry_state is None:
                (long_ok, reason_long), (short_ok, reason_short) = logic.entry_decision(
                    df, i, price, state=entry_state
                )
                if long_ok:
                    side, entry_reason = "long", reason_long
                    entry_price, entry_idx = price, i
                    entry_atr = df["atr"].iloc[i] if "atr" in df.columns else None
                    entry_state = "open"
                    continue
                elif short_ok:
                    side, entry_reason = "short", reason_short
                    entry_price, entry_idx = price, i
                    entry_atr = df["atr"].iloc[i] if "atr" in df.columns else None
                    entry_state = "open"
                    continue

            # --- Exit logic
            else:
                should_exit, exit_reason = logic.exit_decision(
                    df, i, side, price,
                    entry_idx=entry_idx,
                    entry_price=entry_price,
                    entry_atr=entry_atr,
                    entry_reason=entry_reason,
                    state=entry_state
                )
                if should_exit:
                    pnl = (price - entry_price) if side == "long" else (entry_price - price)
                    if entry_atr:
                        pnl_ratio = pnl / entry_atr
                    else:
                        pnl_ratio = pnl / entry_price
                    pnl_usd = pnl_ratio * self.balance * self.position_pct * self.leverage

                    self.balance += pnl_usd
                    self.trades.append({
                        "entry_idx": entry_idx,
                        "exit_idx": i,
                        "entry_price": entry_price,
                        "exit_price": price,
                        "side": side,
                        "pnl": pnl_usd,
                        "entry_reason": entry_reason,
                        "exit_reason": exit_reason,
                    })

                    entry_state = None
                    side = entry_reason = None

        duration = time.time() - start_time

        # --- Performance metrics
        final_balance = self.balance
        total_trades = len(self.trades)
        wins = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]

        roi = ((final_balance - self.starting_balance) / self.starting_balance) * 100
        win_rate = len(wins) / total_trades if total_trades > 0 else 0
        profit_factor = (
            sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses))
            if losses else float("inf")
        )

        sharpe_ratio = compute_sharpe_ratio([t["pnl"] for t in self.trades])
        max_drawdown = compute_max_drawdown([t["pnl"] for t in self.trades])
        streaks = compute_streak_stats([t["pnl"] for t in self.trades])

        # --- Log results to file
        log_path = ensure_dir(f"logs/{self.symbol}_{self.timeframe}.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(summarize_trades(self.trades, self.symbol, self.timeframe))

        self.log(
            f"Completed {self.symbol} {self.timeframe} | "
            f"Trades: {total_trades} | ROI: {roi:.2f}% | PF: {profit_factor:.2f} | Win Rate: {win_rate:.1%}"
        )

        # ✅ Return results with chart compatibility
        trendline_func = None
        if hasattr(self.logic, "calculate_trendlines") and callable(self.logic.calculate_trendlines):
            trendline_func = self.logic.calculate_trendlines

        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "roi_pct": roi,
            "profit_factor": profit_factor,
            "win_rate": win_rate,
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "final_balance": final_balance,
            "starting_balance": self.starting_balance,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "avg_consec_wins": streaks["avg_consec_wins"],
            "avg_consec_losses": streaks["avg_consec_losses"],
            "max_consec_wins": streaks["max_consec_wins"],
            "max_consec_losses": streaks["max_consec_losses"],
            "trades": self.trades,
            "log_file": log_path,

            # 🧩 Added for Plotly interactive chart reporting
            "ohlcv_df": self.df.copy(),
            "trendline_func": trendline_func,
        }


def run_backtest_for(symbols, timeframes, start, end, **kwargs):
    """Run backtest across multiple pairs/timeframes."""
    from bot.core.data_fetch import load_ohlcv

    results = []
    for symbol in symbols:
        for tf in timeframes:
            print(f"\n{Fore.CYAN}→ {symbol} {tf} Backtest{Style.RESET_ALL}")
            df = load_ohlcv(symbol, tf, start, end)
            if df is None or df.empty:
                print(f"{Fore.YELLOW}Skipping {symbol} {tf} (no data){Style.RESET_ALL}")
                continue

            backtest = TFBacktest(
                symbol,
                tf,
                df,
                start_balance=kwargs.get("start_balance", 25.0),
                position_pct=kwargs.get("position_pct", 0.05),
                leverage=kwargs.get("leverage", 10.0),
                debug=kwargs.get("debug", False),
            )
            result = backtest.run()
            results.append(result)

    return results
