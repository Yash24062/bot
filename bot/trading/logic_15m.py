"""
Custom trading logic for 15m timeframe
Boss + Jarvis 2.0
"""

def entry_decision(df, idx, price, trama, macd_hist, atr_pct):
    """
    Entry logic for 15m timeframe:
    - Medium reactivity, avoids minor noise
    - Waits for MACD to have a small buffer before entry
    """
    long_condition = (price > trama) and (macd_hist > 0.0005)
    short_condition = (price < trama) and (macd_hist < -0.0005)
    return long_condition, short_condition


def exit_decision(df, idx, side, price, trama, macd_hist, atr_pct,
                  entry_idx=None, entry_price=None, entry_atr=None, state=None):
    """
    Exit logic for 15m timeframe:
    - Close when MACD crosses opposite with a mild buffer
    - Or if ATR% drops too low (volatility fade-out)
    """
    if side == "long":
        if macd_hist < -0.0003 or atr_pct < 0.0003:
            return True, "MACD_FLIP"
    if side == "short":
        if macd_hist > 0.0003 or atr_pct < 0.0003:
            return True, "MACD_FLIP"
    return False, None
