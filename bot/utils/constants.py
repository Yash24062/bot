"""
Constants and configuration for TRAMA Modular Bot
Author: Jarvis 2.0 (for Boss)
"""

import os

# ------------------ Directory Setup ------------------

DATA_DIR = "data"
REPORT_DIR = "reports"
TRADE_LOG_DIR = "trade_logs"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(TRADE_LOG_DIR, exist_ok=True)

# ------------------ Binance API ------------------

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

TF_TO_MS = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# ------------------ Trading Parameters ------------------

MAKER_FEE = 0.0002
TAKER_FEE = 0.0004

# Risk control
MIN_NOTIONAL = .09
MAX_LEVERAGE_RISK = 0.95

# Backtest parameters
DEFAULT_BALANCE = 25.0
DEFAULT_POSITION_PCT = 0.2
DEFAULT_LEVERAGE = 10.0

# ------------------ Display & Logging ------------------

LOG_COLOR_POSITIVE = "green"
LOG_COLOR_NEGATIVE = "red"
LOG_COLOR_INFO = "cyan"

# ------------------ Metadata ------------------

BOT_NAME = "TRAMA Modular Bot"
VERSION = "2.0"
AUTHOR = "Jarvis 2.0 (for Boss)"
