"""
Custom trading logic for 1D (daily) timeframe
Boss + Jarvis 2.0

Focus: macro trend-following
- Enter on strong breakouts beyond TRAMA with MACD confirmation
- Exit on opposite MACD cross or TRAMA reversion
- Filters low volatility zones
"""

def entry_decision(df, idx, price, trama, macd_hist, atr_pct):
    """
    Entry logic for 1D timeframe:
    - Only trade strong directional breakouts confirmed by MACD
    - Avoid flat volatility environments
    """

    # Skip if volatility too low (no momentum)
    if atr_pct < 0.0008:
        return (False, "LOW_ATR"), (False, "LOW_ATR")

    # Long if price breaks above TRAMA + small buffer and MACD rising
    long_condition = (price > trama * 1.004) and (macd_hist > 0.0008)

    # Short if price breaks below TRAMA - buffer and MACD falling
    short_condition = (price < trama * 0.996) and (macd_hist < -0.0008)

    return (long_condition, "DAILY_TREND_UP"), (short_condition, "DAILY_TREND_DOWN")


def exit_decision(df, idx, side, price, trama, macd_hist, atr_pct,
                  entry_idx=None, entry_price=None, entry_atr=None, state=None):
    """
    Exit logic for 1D timeframe:
    - Exit on trend exhaustion (MACD reversal or TRAMA cross)
    - Incorporates ATR volatility filter for slow momentum decay
    """

    # --- TRAMA cross or MACD reversal ---
    if side == "long":
        if price < trama * 0.998 or macd_hist < -0.0004:
            return True, "TREND_REVERSAL"
    if side == "short":
        if price > trama * 1.002 or macd_hist > 0.0004:
            return True, "TREND_REVERSAL"

    # --- Volatility fade-out exit ---
    if atr_pct < 0.0006:
        return True, "LOW_VOL_EXIT"

    return False, None
