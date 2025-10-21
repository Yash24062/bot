"""
logic_1m_trendline.py — LuxAlgo Hybrid Edition v3.7
Jarvis 2.0 for Boss ⚙️

Upgrades:
    • Replaced ATR-ZigZag with Smart Fractal Pivots (adaptive fractal algorithm)
    • Uses closed-bar fractal detection + ATR-based significance filter
    • Keeps multi-pivot ATR-weighted regression trendlines
    • Non-repainting (pivots confirmed on closed candles)
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

# ==================== CONFIG ==================== #

ATR_LEN = 28
ATR_MULT = 1.0
VOL_CONFIRM_LEN = 30
VOL_SPIKE_MULT = 1.25
BODY_ATR_THRESHOLD = 0.75
ATR_TP_MULT = 1.5
ATR_SL_MULT = 1.0
TIMEOUT_BARS = 20
BOUNCE_TOLERANCE = 0.20
SIDEWAYS_ATR_FACTOR = 0.6

# Smart Fractal pivot settings
SMART_PIVOT_ATR_MULT = 1.2    # require ATR > 1.2 * recent ATR mean at pivot to be significant
SMART_PIVOT_ATR_LEN = 14      # length for ATR short-term baseline used to measure significance

PIVOTS_USED = 3  # number of pivots for regression fit

# ==================== HELPERS ==================== #

def calculate_atr(df, length=14):
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(length).mean()

# ==================== SMART FRACTAL PIVOTS ==================== #

def smart_fractal_pivots(df, atr_mult=SMART_PIVOT_ATR_MULT, atr_len=SMART_PIVOT_ATR_LEN):
    """
    Detect fractal pivots (classic: high greater than neighbors, low less than neighbors)
    and filter them by a short-term ATR significance ratio to ignore tiny noise pivots.

    Non-repainting: uses neighbors (shifted values) and therefore only marks a pivot when
    the center bar is confirmed by its immediate neighbors (closed bars).
    """
    # Ensure ATR exists
    df["atr"] = calculate_atr(df, ATR_LEN)

    # Short-term ATR baseline to measure pivot significance
    df["_atr_short"] = df["atr"].rolling(atr_len, min_periods=1).mean()

    # Classic fractal conditions (pivot at index i if high[i] > high[i-1] and high[i] > high[i+1])
    # We compute booleans for every index (these will be True only when both neighbors exist)
    cond_piv_high = (df["high"] > df["high"].shift(1)) & (df["high"] > df["high"].shift(-1))
    cond_piv_low  = (df["low"]  < df["low"].shift(1))  & (df["low"]  < df["low"].shift(-1))

    # Volatility significance: require ATR at pivot >= atr_mult * recent short ATR mean
    # Use shift(0) because pivot is placed at the bar itself; if you want stricter, use .shift(1)
    vol_ratio = df["atr"] / (df["_atr_short"].replace(0, np.nan))
    signif_high = vol_ratio >= atr_mult
    signif_low  = vol_ratio >= atr_mult

    # Final pivot markers
    pivot_high = (cond_piv_high & signif_high).fillna(False).astype(bool)
    pivot_low  = (cond_piv_low  & signif_low).fillna(False).astype(bool)

    # Clean helper columns (keep 'atr' but drop temporary)
    df.drop(columns=["_atr_short"], inplace=True, errors="ignore")

    df["pivot_high"] = pivot_high
    df["pivot_low"]  = pivot_low
    return df

# ==================== MULTI-PIVOT REGRESSION ==================== #

def multipivot_trendline(df, pivot_col, price_col, n_points=5):
    """Fit ATR-weighted regression line through last N pivots."""
    pivots = df[df[pivot_col]].tail(n_points)
    if len(pivots) < 2:
        return None

    x = pivots.index.values.reshape(-1, 1)
    y = pivots[price_col].values.reshape(-1, 1)

    # Weight by ATR (stronger volatility = more significant)
    # If pivots['atr'] contains NaN, replace with small positive value to avoid crash
    weights = pivots["atr"].fillna(pivots["atr"].median()).values
    # If weights are all zero, fallback to uniform
    if np.all(weights == 0):
        model = LinearRegression().fit(x, y)
    else:
        model = LinearRegression().fit(x, y, sample_weight=weights)

    slope = model.coef_[0][0]
    intercept = model.intercept_[0]
    return slope, intercept

# ==================== TRENDLINE CALCULATION ==================== #

def calculate_trendlines(df):
    """
    Multi-pivot ATR-weighted regression trendlines using Smart Fractal pivots.

    - Detect fractal pivots on closed bars
    - Filter pivots by short-term ATR significance
    - Fit ATR-weighted regression over last PIVOTS_USED pivots
    - Apply small ATR bias to slope to retain dynamic feel
    """
    df = smart_fractal_pivots(df, atr_mult=SMART_PIVOT_ATR_MULT, atr_len=SMART_PIVOT_ATR_LEN)
    # ensure ATR column exists (smart_fractal_pivots left it)
    if "atr" not in df.columns:
        df["atr"] = calculate_atr(df, ATR_LEN)

    slope_atr = df["atr"].iloc[-1] / max(1, ATR_LEN) * ATR_MULT  # small dynamic bias
    up_line = down_line = None

    # --- Uptrend line (pivot lows) ---
    up_slope_data = multipivot_trendline(df, "pivot_low", "low", n_points=PIVOTS_USED)
    if up_slope_data:
        slope, intercept = up_slope_data
        slope += slope_atr  # bias upward
        # anchor intercept at last index's low to keep geometry consistent
        intercept = df["low"].iloc[-1] - slope * df.index[-1]
        up_line = (slope, intercept)

    # --- Downtrend line (pivot highs) ---
    down_slope_data = multipivot_trendline(df, "pivot_high", "high", n_points=PIVOTS_USED)
    if down_slope_data:
        slope, intercept = down_slope_data
        slope -= slope_atr  # bias downward
        intercept = df["high"].iloc[-1] - slope * df.index[-1]
        down_line = (slope, intercept)

    return up_line, down_line

# ==================== ENTRY LOGIC ==================== #

def entry_decision(df, idx, price, trama=None, macd_hist=None, atr_pct=None, state=None):
    if idx < 100:
        return (False, None), (False, None)

    row = df.iloc[idx]
    prev_row = df.iloc[idx - 1]

    if "atr" not in df.columns:
        df["atr"] = calculate_atr(df, ATR_LEN)
    atr = df["atr"].iloc[idx]

    avg_vol = df["volume"].iloc[max(0, idx - VOL_CONFIRM_LEN):idx].mean()
    vol_ok = row["volume"] > avg_vol
    vol_spike = row["volume"] > avg_vol * VOL_SPIKE_MULT
    body_ok = abs(row["close"] - row["open"]) > BODY_ATR_THRESHOLD * atr

    if not (vol_ok and vol_spike and body_ok):
        return (False, "VOL_OR_BODY_FAIL"), (False, "VOL_OR_BODY_FAIL")

    if idx > 50:
        atr_median_50 = df["atr"].iloc[max(0, idx - 50):idx].median()
        if atr < atr_median_50 * SIDEWAYS_ATR_FACTOR:
            return (False, "SIDEWAYS_ATR_LOW"), (False, "SIDEWAYS_ATR_LOW")

    recent_df = df.iloc[max(0, idx - 150):idx].copy()
    up_line, down_line = calculate_trendlines(recent_df)

    long_ok = short_ok = False
    reason_long = reason_short = None

    # --- Breakout Logic ---
    if down_line:
        slope, intercept = down_line
        trend_val = slope * idx + intercept
        if prev_row["close"] <= trend_val and row["close"] > trend_val:
            long_ok = True
            reason_long = "LUX_BREAKOUT_UP"

    if up_line:
        slope, intercept = up_line
        trend_val = slope * idx + intercept
        if prev_row["close"] >= trend_val and row["close"] < trend_val:
            short_ok = True
            reason_short = "LUX_BREAKOUT_DOWN"

    # --- Bounce Logic ---
    if up_line:
        slope, intercept = up_line
        trend_val = slope * idx + intercept
        if (row["low"] <= trend_val + atr * BOUNCE_TOLERANCE) and (row["close"] > trend_val):
            long_ok = True
            reason_long = "LUX_BOUNCE_UP"

    if down_line:
        slope, intercept = down_line
        trend_val = slope * idx + intercept
        if (row["high"] >= trend_val - atr * BOUNCE_TOLERANCE) and (row["close"] < trend_val):
            short_ok = True
            reason_short = "LUX_BOUNCE_DOWN"

    return (long_ok, reason_long), (short_ok, reason_short)

# ==================== EXIT LOGIC ==================== #

def exit_decision(df, idx, side, price,
                  trama=None, macd_hist=None, atr_pct=None,
                  entry_idx=None, entry_price=None, entry_atr=None,
                  state=None, entry_reason=None):

    if entry_idx is None:
        return False, None

    row = df.iloc[idx]
    atr = row.get("atr", np.nan)

    if entry_reason in ["LUX_BOUNCE_UP", "LUX_BOUNCE_DOWN"]:
        tp_mult = 1.0
        sl_mult = 0.7
    else:
        tp_mult = ATR_TP_MULT
        sl_mult = ATR_SL_MULT

    tp_price = entry_price + tp_mult * atr if side == "long" else entry_price - tp_mult * atr
    sl_price = entry_price - sl_mult * atr if side == "long" else entry_price + sl_mult * atr

    if side == "long" and price >= tp_price:
        return True, f"TP ({entry_reason or 'Breakout'})"
    if side == "long" and price <= sl_price:
        return True, f"SL ({entry_reason or 'Breakout'})"
    if side == "short" and price <= tp_price:
        return True, f"TP ({entry_reason or 'Breakout'})"
    if side == "short" and price >= sl_price:
        return True, f"SL ({entry_reason or 'Breakout'})"

    if idx - entry_idx >= TIMEOUT_BARS:
        return True, "TIMEOUT"

    return False, None
