# ================================================================
#  config.py — All bot settings in one place
# ================================================================

# ── Market ────────────────────────────────────────────────────────
SYMBOL              = "BTC/USDT:USDT"      # Trading pair
DISPLAY             = "BTC"                # Short name for display
LEVERAGE            = 10                   # 10x margin (use 1 for spot)

# ── Timing ────────────────────────────────────────────────────────
FETCH_INTERVAL      = 2                    # seconds between display updates
TRADE_HISTORY_LEN   = 100                  # how many recent trades to keep

# ── Orderbook Analysis ────────────────────────────────────────────
BIN_PCT             = 0.0001               # 0.01% bucket size for pooling
CHART_LEVELS        = 20                   # max depth levels to display
BIG_WALL_MULTIPLIER = 3.0                  # wall = 3× average bucket qty
MIN_ZONE_STRENGTH   = 3                    # min buckets in a cluster
ZONE_CONFIRM_SNAPS  = 3                    # snapshots before zone confirmed
ZONE_MISS_LIMIT     = 10                   # snapshots before zone removed
ZONE_PROXIMITY_PCT  = 0.0003               # 0.03% = zone touch distance

# ── Momentum ──────────────────────────────────────────────────────
MOMENTUM_WINDOW     = 20                   # rolling window size
VOLUME_SPIKE_MULT   = 1.5                  # vol > avg × 1.5 = spike
IMBALANCE_THRESHOLD = 0.60                 # bid/total > 0.60 = bullish

# ── Entry signals ────────────────────────────────────────────────
REVERSAL_TOUCHES_NEEDED = 2                # touches before reversal signal
TOUCH_COOLDOWN_PCT  = 0.001                # 0.1% cooldown between touches

# ── Anti-spoof ────────────────────────────────────────────────────
SPOOF_DROP_PCT      = 0.5                  # 50% sudden drop = suspected spoof
SPOOF_CONFIRM_SNAPS = 2                    # snaps of big drops before flag
SPOOF_RECOVER_SNAPS = 3                    # snaps stable to clear flag

# ── TP / SL ──────────────────────────────────────────────────────
MIN_RR_RATIO        = 1.5                  # reward / risk ratio minimum
TP_FALLBACK_PCT     = 0.005                # 0.5% if no zone qualifies
SL_FALLBACK_PCT     = 0.005                # 0.5% if no zone qualifies
TP_SKIP_TO_NEXT     = True                 # skip low-RR zones, try next

# ── Trading ───────────────────────────────────────────────────────
TRADE_SIZE_USDT     = 10                   # margin per trade (USD)
STARTING_BALANCE    = 1000                 # paper trading starting cash
TAKER_FEE_PCT       = 0.0004               # 0.04% on entry + exit
ALLOW_REENTRY       = True                 # allow 1 re-entry per stop
