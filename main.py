# ================================================================
#  main.py — Start here.  python main.py
# ================================================================

import time
import sys
from config    import FETCH_INTERVAL, DISPLAY, LEVERAGE
from data_feed import DataFeed
from analysis  import Analyser
from trader    import Trader
import display as ui


def main():
    print(f"\n  🤖  LIQUIDITY BOT — {DISPLAY} | {LEVERAGE}x | Paper Mode")
    print("  Connecting to Binance Futures...\n")

    feed       = DataFeed()
    analyser   = Analyser()
    trader     = Trader()
    action_log = []
    MAX_LOG_SIZE = 1000  # FIX: Prevent unbounded memory growth

    feed.start()

    # Wait for first data
    for _ in range(15):
        time.sleep(1)
        if feed.connected:
            break
    else:
        print("  ❌ Could not connect. Check your internet.")
        sys.exit(1)

    print(f"  ✅ Connected!  Mid price: ${feed.get_mid_price():,.2f}")
    print("  Starting in 2 seconds...\n")
    time.sleep(2)

    try:
        while True:
            orderbook = feed.get_orderbook()
            trades    = feed.get_trades()
            mid_price = feed.get_mid_price()

            if mid_price == 0:
                time.sleep(FETCH_INTERVAL)
                continue

            analyser.update(orderbook, trades, mid_price)
            signals = analyser.get_signals(mid_price)

            new_actions = trader.evaluate(signals, mid_price)
            if new_actions:
                action_log.extend(new_actions)
                # FIX: Keep log size bounded (trimmed FIFO if exceeded)
                if len(action_log) > MAX_LOG_SIZE:
                    action_log = action_log[-MAX_LOG_SIZE:]

            ui.render(
                orderbook  = orderbook,
                zones      = analyser.zones,
                momentum   = analyser.momentum,
                signals    = signals,
                trader     = trader,
                mid_price  = mid_price,
                trades     = list(trades),
                action_log = action_log,
            )

            time.sleep(FETCH_INTERVAL)

    except KeyboardInterrupt:
        s = trader.summary()
        print(f"\n\n  ⏹  Stopped.")
        print(f"  Trades : {s['trades']}  W/L : {s['wins']}/{s['losses']}  "
              f"WR : {s['win_rate']:.1f}%")
        print(f"  Balance : ${s['balance']:,.4f}  "
              f"Fees : ${s['total_fees']:,.4f}  "
              f"Net PnL : ${s['balance'] - 1000:+,.4f}\n")


if __name__ == "__main__":
    main()
