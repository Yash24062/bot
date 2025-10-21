"""
Data fetching and validation for TRAMA Modular Bot
Author: Jarvis 2.0 (for Boss)
"""

from __future__ import annotations
import os
import time
from datetime import datetime
from typing import List, Tuple

import numpy as np
import pandas as pd
import requests
from tqdm import tqdm

from bot.utils.constants import DATA_DIR, BINANCE_KLINES_URL, TF_TO_MS
from bot.utils.time_utils import dt_to_millis, millis_to_dt
from bot.core.logging_utils import log_warning, log_info, log_error

# Ensure data dir exists (constants already creates it, but safe)
os.makedirs(DATA_DIR, exist_ok=True)


def validate_ohlc_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """
    Validate OHLC data and return cleaned DataFrame with list of warnings.
    Expects a DataFrame with columns: ['timestamp','open','high','low','close','volume']
    'timestamp' should be datetime-like or will be converted.
    """
    warnings: List[str] = []
    original_len = len(df)
    df = df.copy()

    # Ensure timestamp column is datetime
    if 'timestamp' not in df.columns:
        raise ValueError("DataFrame missing 'timestamp' column")

    if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
        try:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        except Exception as e:
            raise ValueError(f"Failed to parse timestamps: {e}")

    # Localize / convert timestamps to UTC tz-aware datetimes
    try:
        if df['timestamp'].dt.tz is None:
            df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
        else:
            df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
    except Exception:
        df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize('UTC')

    # Check for missing values
    null_count = int(df.isnull().sum().sum())
    if null_count > 0:
        warnings.append(f"Found {null_count} missing values - forward filling")
        df = df.ffill()

    # Ensure numeric types for price columns
    price_cols = ['open', 'high', 'low', 'close']
    for col in price_cols:
        if col not in df.columns:
            raise ValueError(f"Data missing required column: {col}")
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Remove zero or negative price rows
    for col in price_cols:
        invalid_count = int((df[col] <= 0).sum())
        if invalid_count > 0:
            warnings.append(f"Found {invalid_count} rows with non-positive '{col}' - removing")
            df = df[df[col] > 0]

    # Fix rows where high < low
    invalid_high_low = int((df['high'] < df['low']).sum())
    if invalid_high_low > 0:
        warnings.append(f"Found {invalid_high_low} rows with high < low - fixing high = low + tiny_eps")
        df.loc[df['high'] < df['low'], 'high'] = df.loc[df['high'] < df['low'], 'low'] + 1e-9

    # Sort by timestamp
    df = df.sort_values('timestamp').reset_index(drop=True)

    # Check timestamp continuity and gaps
    if len(df) > 2:
        time_diffs = df['timestamp'].diff().dt.total_seconds().dropna()
        try:
            expected_interval = int(time_diffs.mode().iloc[0])
        except Exception:
            expected_interval = int(time_diffs.median())
        gaps = (time_diffs > expected_interval * 1.5).sum()
        if gaps > 0:
            warnings.append(f"Found {int(gaps)} large timestamp gaps (>1.5x expected interval)")

    # Remove duplicate timestamps
    dup_count = int(df.duplicated(subset=['timestamp']).sum())
    if dup_count > 0:
        warnings.append(f"Found {dup_count} duplicate timestamps - removing")
        df = df.drop_duplicates(subset=['timestamp']).reset_index(drop=True)

    final_len = len(df)
    if final_len < original_len:
        warnings.append(f"Removed {original_len - final_len} invalid rows during validation")

    return df, warnings


def fetch_klines_binance(symbol: str, interval: str, start_dt: datetime, end_dt: datetime, cache: bool = True) -> pd.DataFrame:
    """
    Fetch klines/candles from Binance public API between start_dt and end_dt (UTC datetimes).
    Caches to CSV in DATA_DIR to avoid repeated network calls.
    Returns a DataFrame with columns: ['timestamp','open','high','low','close','volume'] where
    'timestamp' is timezone-aware UTC datetime dtype.
    """
    start_ms = dt_to_millis(start_dt)
    end_ms = dt_to_millis(end_dt)
    safe_symbol = symbol.upper()
    fname = os.path.join(DATA_DIR, f"{safe_symbol}_{interval}_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.csv")

    # Return from cache if present
    if cache and os.path.exists(fname):
        try:
            df = pd.read_csv(fname, parse_dates=['timestamp'])
            if df['timestamp'].dt.tz is None:
                df['timestamp'] = df['timestamp'].dt.tz_localize('UTC')
            df, warnings = validate_ohlc_data(df)
            if warnings:
                for w in warnings:
                    log_warning(f"{symbol} {interval} cache warning: {w}")
            log_info(f"Loaded cached data: {fname} ({len(df)} rows)")
            return df
        except Exception as e:
            log_warning(f"Failed to load cache {fname}: {e} — will re-fetch")

    limit = 1000
    rows = []
    cur = start_ms

    with tqdm(desc=f"Fetching {symbol} {interval}", unit="batch") as pbar:
        while cur < end_ms:
            params = {
                "symbol": safe_symbol,
                "interval": interval,
                "startTime": cur,
                "endTime": end_ms,
                "limit": limit,
            }
            try:
                r = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                if not data:
                    break

                for item in data:
                    ts = item[0]
                    rows.append([
                        millis_to_dt(ts),
                        float(item[1]), float(item[2]), float(item[3]),
                        float(item[4]), float(item[5])
                    ])

                last_ts = data[-1][0]
                cur = last_ts + TF_TO_MS.get(interval, 60_000)
                pbar.update(1)
                time.sleep(0.12)

            except requests.exceptions.RequestException as e:
                log_error(f"Network error fetching {symbol} {interval}: {e}")
                break
            except Exception as e:
                log_error(f"Unexpected error fetching {symbol} {interval}: {e}")
                break

    if not rows:
        raise ValueError(f"No data fetched for {symbol} {interval} between {start_dt} and {end_dt}")

    df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_convert('UTC')

    df, warnings = validate_ohlc_data(df)
    if warnings:
        for w in warnings:
            log_warning(f"{symbol} {interval} fetch warning: {w}")

    if cache and len(df) > 0:
        try:
            df.to_csv(fname, index=False)
            log_info(f"Cached fetched data to: {fname}")
        except Exception as e:
            log_warning(f"Failed to write cache file {fname}: {e}")

    return df


# ==============================
#  ADDED: load_ohlcv() WRAPPER
# ==============================

def load_ohlcv(symbol: str, timeframe: str, start: datetime, end: datetime, cache: bool = True) -> pd.DataFrame:
    """
    Unified wrapper for backtester compatibility.
    Loads OHLCV data for symbol/timeframe via cache or Binance fetcher.
    """
    try:
        df = fetch_klines_binance(symbol, timeframe, start, end, cache=cache)
        return df
    except Exception as e:
        log_error(f"load_ohlcv() failed for {symbol} {timeframe}: {e}")
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
