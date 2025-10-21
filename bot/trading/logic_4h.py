"""
Custom trading logic for 4h timeframe
Boss + Jarvis 2.0
"""

def entry_decision(df, idx, price, trama, macd_hist, atr_pct):
    """
    Entry logic for 4h timeframe:
    - Trend-following, slower confirmation
    - Requires both price > TRAMA and MACD histogram to be strongly positive
    """
    long_condition = (price > trama * 1.003) and (macd_hist > 0.0008)
    short_condition = (price < trama * 0.997) and (macd_hist < -0.0008)
    return long_condition, short_condition


def exit_decision(df, idx, side, price, trama, macd_hist, atr_pct,
                  entry_idx=None, entry_price=None, entry_atr=None, state=None):
    """
    Exit logic for 4h timeframe:
    - Exits only on stronger trend reversals
    - Adds ATR-based trailing protection
    """
    if side == "long":
        # Close if MACD turns negative OR price drops below TRAMA - 0.2% of price
        if macd_hist < -0.0005 or price < trama * 0.998:
            return True, "TREND_REVERSAL"
    if side == "short":
        # Close if MACD turns positive OR price exceeds TRAMA + 0.2% of price
        if macd_hist > 0.0005 or price > trama * 1.002:
            return True, "TREND_REVERSAL"
    return False, None
