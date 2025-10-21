"""
Indicator calculations for TRAMA and Scalper Logic
Upgraded — Jarvis 2.0 (for Boss)
Now includes:
    ✅ 1-Hour EMA200 alignment support for scalper trend confirmation
"""

import pandas as pd
import numpy as np
from colorama import Fore, Style

# ------------------ LuxAlgo TRAMA ------------------

def lux_algo_trama(df: pd.DataFrame, length: int = 99, source: str = "close") -> pd.Series:
    """
    LuxAlgo TRAMA (Trend Regularity Adaptive Moving Average)
    Original concept adapted from TradingView: https://www.tradingview.com/script/whdw1EdR/
    """
    src = df[source] if source in df else df["close"]
    highest = src.rolling(window=length, min_periods=length).max()
    lowest = src.rolling(window=length, min_periods=length).min()
    hh = (highest.diff() > 0).astype(int)
    ll = (lowest.diff() < 0).astype(int)
    trend_bin = ((hh + ll) > 0).astype(int)
    trend_reg = trend_bin.rolling(window=length, min_periods=length).mean()
    tc = trend_reg ** 2

    ama = [src.iloc[0]]
    for i in range(1, len(df)):
        if pd.isna(tc.iloc[i]) or pd.isna(src.iloc[i]):
            ama.append(ama[-1])
            continue
        alpha = max(min(tc.iloc[i], 1.0), 0.0)
        ama.append(ama[-1] + alpha * (src.iloc[i] - ama[-1]))
    return pd.Series(ama, index=df.index)

# ------------------ MACD ------------------

def calculate_macd(df: pd.DataFrame, fast=12, slow=26, signal=9):
    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line, macd_signal, macd_hist

# ------------------ ATR ------------------

def calculate_atr(df: pd.DataFrame, length=14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(length, min_periods=1).mean()

# ------------------ Combined Indicators ------------------

def add_indicators(df: pd.DataFrame, trama_len: int = 99) -> pd.DataFrame:
    """
    Compute indicators for both TRAMA and high-win scalper logic.
    Automatically provides:
      - TRAMA, MACD, ATR (for older logic)
      - EMA20/EMA50, RSI(6), Volume Z-score (for 5m scalper)
      - EMA200 (1h) trend alignment (for EMA alignment filter)
    """
    print(f"{Fore.CYAN}Calculating indicators...{Style.RESET_ALL}")
    try:
        # --- ATR + ATR% ---
        df["atr"] = calculate_atr(df)
        df["atr_pct"] = df["atr"] / df["close"]

        # --- TRAMA & MACD (legacy strategies) ---
        df["trama"] = lux_algo_trama(df, trama_len)
        macd_line, macd_signal, macd_hist = calculate_macd(df)
        df["macd_hist"] = macd_hist

        # --- EMA & RSI & Volume Z-score (scalper logic) ---
        df["ema_fast"] = df["close"].ewm(span=20, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=50, adjust=False).mean()

        delta = df["close"].diff()
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).rolling(6).mean()
        avg_loss = pd.Series(loss).rolling(6).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        vol_mean = df["volume"].rolling(20).mean()
        vol_std = df["volume"].rolling(20).std()
        df["vol_z"] = (df["volume"] - vol_mean) / (vol_std + 1e-9)

        # --- Higher Timeframe EMA200 (1h) for trend alignment ---
        if "timestamp" in df.columns:
            df_1h = (
                df.resample("1h", on="timestamp", label="right", closed="right")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna()
                .reset_index()
            )

            df_1h["ema_200_1h"] = df_1h["close"].ewm(span=200, adjust=False).mean()

            # Merge back into 5m df using nearest previous timestamp
            df = pd.merge_asof(
                df.sort_values("timestamp"),
                df_1h[["timestamp", "ema_200_1h"]].sort_values("timestamp"),
                on="timestamp",
                direction="backward"
            )
            print(f"{Fore.YELLOW}✓ Added 1h EMA200 for macro trend alignment.{Style.RESET_ALL}")
        else:
            print(f"{Fore.YELLOW}⚠️ No timestamp column found; skipping 1h EMA200.{Style.RESET_ALL}")

        df.dropna(inplace=True)
        print(f"{Fore.GREEN}✓ Indicators ready (TRAMA + Scalper + 1h EMA200).{Style.RESET_ALL}")
        return df.reset_index(drop=True)

    except Exception as e:
        print(f"{Fore.RED}Error calculating indicators: {e}{Style.RESET_ALL}")
        raise
