"""
logic_5m.py — High-Win Scalper v2.3 (Adaptive EMA Slope Edition)
Jarvis 2.0 for Boss ⚙️

Core logic:
    Momentum burst + micro pullback continuation
    Adaptive EMA slope alignment instead of strict EMA crossover

Upgrades:
    ✅ Uses EMA slope to detect directional momentum
    ✅ EMA alignment enforced only when RSI confidence is low (neutral zone)
    ✅ Retains macro EMA200 (1h) directional filter
    ✅ Still filters low-volatility or dead-volume conditions
"""

import numpy as np
import pandas as pd


# ==================== CONFIG ==================== #

EMA_FAST = 20
EMA_SLOW = 50
EMA_HTF = 200           # 1-hour EMA for macro trend bias
RSI_LEN = 6
VOL_WINDOW = 20
ATR_LEN = 14
ATR_TP_MULT = 0.6
ATR_SL_MULT = 0.8
TIMEOUT_BARS = 20
RSI_EXIT_ZONE = 50
VOL_Z_MIN = 0.8
ATR_MIN_THRESH = 0.0007
RSI_CONF_NEUTRAL = 10    # range around 50 considered neutral


# ==================== ENTRY LOGIC ==================== #

def entry_decision(df, idx, price, trama=None, macd_hist=None, atr_pct=None):
    """
    Entry decision for 5m scalper with adaptive EMA slope alignment.
    - EMA slope-based direction instead of strict crossover
    - EMA filter activates only when RSI confidence is low (≈50)
    - 5m + 1h macro trend agreement maintained
    """
    if idx < EMA_SLOW + VOL_WINDOW:
        return (False, None), (False, None)

    row = df.iloc[idx]
    prev_row = df.iloc[idx - 1]

    ema_fast = row["ema_fast"]
    ema_slow = row["ema_slow"]
    ema_fast_prev = prev_row["ema_fast"]
    ema_slow_prev = prev_row["ema_slow"]

    ema_fast_slope = ema_fast - ema_fast_prev
    ema_slow_slope = ema_slow - ema_slow_prev

    rsi_val = row["rsi"]
    rsi_confidence = abs(rsi_val - 50)

    vol_ok = row["vol_z"] > VOL_Z_MIN
    atr_ok = row["atr_pct"] > ATR_MIN_THRESH

    # Skip low volume / low volatility
    if not (vol_ok and atr_ok):
        return (False, "LOW_VOL_OR_ATR"), (False, "LOW_VOL_OR_ATR")

    # Macro confirmation (1h EMA200)
    if "ema_200_1h" not in df.columns:
        macro_up = True
        macro_down = True
    else:
        macro_up = price > row["ema_200_1h"]
        macro_down = price < row["ema_200_1h"]

    # --- Adaptive EMA alignment logic ---
    if rsi_confidence < RSI_CONF_NEUTRAL:
        # RSI near neutral → trust EMA slope for direction
        trend_up = (ema_fast > ema_slow) and (ema_fast_slope > 0)
        trend_down = (ema_fast < ema_slow) and (ema_fast_slope < 0)
    else:
        # RSI shows clear bias → skip EMA restriction
        trend_up = rsi_val > 55
        trend_down = rsi_val < 45

    # Require macro + local direction agreement
    if not (trend_up and macro_up) and not (trend_down and macro_down):
        return (False, "NO_TREND_ALIGNMENT"), (False, "NO_TREND_ALIGNMENT")

    # Momentum burst detection
    vol_impulse = row["vol_z"] > 1.5

    # Pullback check (price near EMA20)
    prev_close = df["close"].iloc[idx - 1]
    ema_diff = abs(prev_close - ema_fast)
    pullback_ok = ema_diff < 0.5 * row["atr"]

    # Final conditions
    long_ok = trend_up and macro_up and vol_impulse and pullback_ok and rsi_val > 50
    short_ok = trend_down and macro_down and vol_impulse and pullback_ok and rsi_val < 50

    return (long_ok, "SCALP_LONG_TREND"), (short_ok, "SCALP_SHORT_TREND")


# ==================== EXIT LOGIC ==================== #

def exit_decision(df, idx, side, price, trama=None, macd_hist=None, atr_pct=None,
                  entry_idx=None, entry_price=None, entry_atr=None, state=None):
    """Standard scalper exits (small TP/SL + RSI timeout)"""
    if entry_idx is None:
        return False, None

    row = df.iloc[idx]
    atr = row["atr"]

    tp_price = entry_price + ATR_TP_MULT * atr if side == "long" else entry_price - ATR_TP_MULT * atr
    sl_price = entry_price - ATR_SL_MULT * atr if side == "long" else entry_price + ATR_SL_MULT * atr

    # Hard stop-loss / take-profit
    if side == "long" and price >= tp_price:
        return True, "TP"
    if side == "long" and price <= sl_price:
        return True, "SL"
    if side == "short" and price <= tp_price:
        return True, "TP"
    if side == "short" and price >= sl_price:
        return True, "SL"

    # Timeout exit
    if idx - entry_idx >= TIMEOUT_BARS:
        return True, "TIMEOUT"

    # RSI exit (momentum loss)
    if side == "long" and row["rsi"] < RSI_EXIT_ZONE:
        return True, "RSI_FLIP"
    if side == "short" and row["rsi"] > RSI_EXIT_ZONE:
        return True, "RSI_FLIP"

    return False, None
