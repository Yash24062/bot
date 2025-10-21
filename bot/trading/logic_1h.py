"""
Custom trading logic for 1h timeframe
Boss + Jarvis 2.0
"""

def entry_decision(df, idx, price, trama, macd_hist, atr_pct):
    """
    Entry logic for 1h timeframe:
    - Focus on clearer trends
    - Require price to be significantly above/below TRAMA
    """
    long_condition = (price > trama * 1.002) and (macd_hist > 0)
    short_condition = (price < trama * 0.998) and (macd_hist < 0)
    return long_condition, short_condition


def exit_decision(df, idx, side, price, trama, macd_hist, atr_pct,
                  entry_idx=None, entry_price=None, entry_atr=None, state=None):
    """
    Exit logic for 1h timeframe:
    - Closes slower than 15m
    - Exit if price crosses back over TRAMA or MACD flips
    """
    if side == "long":
        if price < trama or macd_hist < 0:
            return True, "TREND_REVERSAL"
    if side == "short":
        if price > trama or macd_hist > 0:
            return True, "TREND_REVERSAL"
    return False, None
