# ================================================================
#  display.py — Single terminal display
#               Sections (scroll up to see all):
#                 1. Header + momentum
#                 2. Orderbook depth chart (binned 0.01% buckets)
#                 3. Live market trades
#                 4. Confirmed liquidity zones
#                 5. Active signals
#                 6. Open position detail
#                 7. Paper wallet + closed trades
# ================================================================

import os
from datetime import datetime
from collections import defaultdict
from config import (
    DISPLAY, LEVERAGE, TAKER_FEE_PCT,
    STARTING_BALANCE, BIN_PCT, CHART_LEVELS
)

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"
C = "\033[96m"; B = "\033[1m";  D = "\033[2m"
RESET = "\033[0m"
BAR_MAX = 40


def clear():
    os.system("cls" if os.name == "nt" else "clear")


# ── Section renderers ───────��─────────────────────────────────────

def _header(mid_price, momentum):
    now  = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    bias = momentum.get("bias", "neutral")
    bc   = G if bias == "bull" else (R if bias == "bear" else Y)
    imb  = momentum.get("imbalance", 0.5)
    spike = f"{Y}⚡ YES{RESET}" if momentum.get("volume_spike") else f"{D}no{RESET}"

    print(f"{B}{C}{'═'*72}{RESET}")
    print(f"{B}{C}  🤖  LIQUIDITY BOT  |  {DISPLAY}  |  {LEVERAGE}x  |  {now}{RESET}")
    print(f"{B}{C}{'═'*72}{RESET}")
    print(f"  Price : {B}${mid_price:,.4f}{RESET}   "
          f"Bias : {bc}{B}{bias.upper()}{RESET}   "
          f"OB Imbalance : {imb:.1%}   "
          f"Vol Spike : {spike}")
    print(f"  Bid Vol : {momentum.get('bid_vol',0):.3f}   "
          f"Ask Vol : {momentum.get('ask_vol',0):.3f}   "
          f"Recent Vol : {momentum.get('recent_vol',0):.4f}   "
          f"Avg Vol : {momentum.get('avg_vol',0):.4f}\n")


def _bin_side(levels, mid_price, side):
    if not levels or mid_price == 0:
        return []
    bw   = mid_price * BIN_PCT
    bins = defaultdict(float)
    for price, qty in levels:
        bucket = round(price / bw) * bw
        bins[bucket] += qty
    result = sorted(bins.items(), key=lambda x: x[0],
                    reverse=(side == "bid"))
    return result[:CHART_LEVELS]


def _orderbook(bids, asks, mid_price, zones):
    zone_mids = [z.price_mid for z in zones]

    binned = (
        [("ask", p, q) for p, q in _bin_side(asks, mid_price, "ask")] +
        [("bid", p, q) for p, q in _bin_side(bids, mid_price, "bid")]
    )
    binned.sort(key=lambda x: x[1], reverse=True)

    if not binned:
        print(f"  {D}Waiting for orderbook...{RESET}\n")
        return

    max_qty = max(q for _, _, q in binned) or 1

    print(f"  {B}ORDERBOOK — 0.01% pooled buckets  (★ confirmed zone  ◀ mid){RESET}")
    print(f"  {'Price':>14}  {'Qty':>10}  {'Bar':40}")
    print(f"  {'─'*14}  {'─'*10}  {'─'*40}")

    for side, price, qty in binned:
        bar  = "█" * max(1, int(qty / max_qty * BAR_MAX))
        col  = G if side == "bid" else R
        lbl  = "BID" if side == "bid" else "ASK"
        star = (f" {Y}★{RESET}" if any(
            abs(price - zm) / max(zm, 1) < BIN_PCT * 6 for zm in zone_mids)
            else "  ")
        mid  = (f" {C}◀ MID{RESET}" if abs(price - mid_price) / max(mid_price, 1)
                < BIN_PCT * 3 else "")
        qstr = f"{qty:>10.2f}" if qty >= 1 else f"{qty:>10.4f}"
        print(f"  {col}{price:>14,.4f}{RESET}  {qstr}  "
              f"{col}{bar:<40}{RESET}{star}{mid}  {col}{lbl}{RESET}")
    print()


def _live_trades(trades):
    print(f"  {B}LIVE MARKET TRADES{RESET}")
    if not trades:
        print(f"  {D}  No trades yet...{RESET}\n")
        return
    print(f"  {'Side':4}  {'Price':>12}  {'Amount':>12}  {'Value':>14}")
    print(f"  {'─'*4}  {'─'*12}  {'─'*12}  {'─'*14}")
    for t in reversed(trades[-12:]):
        col = G if t.get("side") == "buy" else R
        val = t["price"] * t["amount"]
        print(f"  {col}{t['side'].upper():4}{RESET}  "
              f"{col}{t['price']:>12,.4f}{RESET}  "
              f"{t['amount']:>12.6f}  ${val:>13,.2f}")
    print()


def _zones(zones, mid_price):
    print(f"  {B}CONFIRMED LIQUIDITY ZONES{RESET}")
    if not zones:
        print(f"  {D}  Building zone registry... (needs strength to lock){RESET}\n")
        return
    print(f"  {'Side':5} {'Price':>12} {'Band':>11} {'Qty':>9} {'Strength':8} "
          f"{'Visits':7} {'Broken':7} {'Dist':6}")
    print(f"  {'─'*5} {'─'*12} {'─'*11} {'─'*9} {'─'*8} "
          f"{'─'*7} {'─'*7} {'─'*6}")
    for z in zones[:8]:
        col  = G if z.side == "bid" else R
        brk  = f"{R}BROKEN{RESET}" if z.broken else f"{G}intact{RESET}"
        spf  = f" {Y}⚠SPOOF{RESET}" if getattr(z, 'suspected_spoof', False) else ""
        dist = z.distance_to_zone(mid_price) / max(z.price_mid, 1) * 100
        band = f"${z.price_low:,.2f}-${z.price_high:,.2f}"
        strength = f"{z.strength_score:.1f}/10"
        print(f"  {col}{z.side.upper():5}{RESET} "
              f"{col}{z.price_mid:>12,.2f}{RESET} "
              f"{band:>11} "
              f"{z.latest_qty:>9.3f} "
              f"{strength:8} "
              f"{'★'*min(z.touches,5):7} "
              f"{brk}  {dist:.3f}%{spf}")
    print()


def _signals(signals):
    print(f"  {B}ACTIVE SIGNALS{RESET}")
    if not signals:
        print(f"  {D}  Waiting for setup...{RESET}\n")
        return
    for sig in signals[:3]:
        sc   = G if sig["side"] == "BUY" else R
        rr   = sig.get("rr", 0)
        rrc  = G if rr >= 2.0 else (Y if rr >= 1.5 else R)
        skip = sig.get("tp_skip")
        print(f"  {sc}{B}{sig['side']:4}{RESET} | {sig['type']:16} | "
              f"TP {G}${sig['tp']:,.2f}{RESET}  SL {R}${sig['sl']:,.2f}{RESET} | "
              f"R:R {rrc}{rr:.2f}{RESET} | {D}{sig['reason']}{RESET}")
        if skip:
            print(f"    {D}⚠  {skip}{RESET}")
    print()


def _position(pos, mid_price):
    print(f"  {B}OPEN POSITION{RESET}")
    if not pos:
        print(f"  {D}  No open position.{RESET}\n")
        return
    upnl  = pos.unrealised_pnl(mid_price)
    uc    = G if upnl >= 0 else R
    liq   = pos.liquidation_price()
    sc    = G if pos.side == "BUY" else R

    print(f"  {sc}{B}{pos.side}{RESET} @ ${pos.entry_price:,.4f}  |  "
          f"Margin ${pos.margin:.2f}  ×{LEVERAGE}  =  Notional ${pos.notional:.2f}  |  "
          f"Qty {pos.qty:.6f}")
    print(f"  TP  : {G}${pos.tp:,.4f}{RESET}  ← nearest zone above entry clearing fees")
    print(f"  SL  : {R}${pos.sl:,.4f}{RESET}  ← nearest zone below entry")
    print(f"  Liq : {R}${liq:,.4f}{RESET}  ← full margin wipe (-10% from entry)")
    print(f"  Fee : {Y}${pos.entry_fee:.4f}{RESET}  "
          f"({TAKER_FEE_PCT*100:.2f}% × ${pos.notional:.2f})  |  "
          f"uPnL : {uc}{B}{upnl:+.4f} USDT{RESET}")
    if pos.tp_zone:
        print(f"  {D}  TP zone → {pos.tp_zone}{RESET}")
    if pos.sl_zone:
        print(f"  {D}  SL zone → {pos.sl_zone}{RESET}")
    print()


def _wallet(trader, mid_price, action_log):
    s      = trader.summary()
    total  = trader.total_value(mid_price)
    net    = total - STARTING_BALANCE
    pc     = G if net >= 0 else R

    print(f"  {B}PAPER WALLET{RESET}")
    print(f"  Balance : ${trader.balance:>10,.4f}   "
          f"Total : {pc}${total:>10,.4f}{RESET}   "
          f"Net PnL : {pc}{net:>+.4f}{RESET}")
    print(f"  Fees    : {Y}${s['total_fees']:>8,.4f}{RESET}   "
          f"Trades : {s['trades']}   "
          f"W/L : {G}{s['wins']}{RESET}/{R}{s['losses']}{RESET}   "
          f"WR : {s['win_rate']:.0f}%\n")

    if action_log:
        print(f"  {B}RECENT ACTIONS{RESET}")
        for a in action_log[-4:]:
            print(f"  {Y}▶{RESET} {a}")
        print()

    if trader.trade_log:
        print(f"  {B}CLOSED TRADES{RESET}")
        print(f"  {'Time':8} {'Side':4} {'Entry':>10} {'Exit':>10} "
              f"{'PnL':>10} {'Fees':>8} {'Reason'}")
        print(f"  {'─'*8} {'─'*4} {'─'*10} {'─'*10} {'─'*10} {'─'*8} {'─'*12}")
        for t in trader.trade_log[-6:]:
            pc2 = G if t["pnl"] >= 0 else R
            print(f"  {t['time']:8} {t['side']:4} "
                  f"${t['entry']:>9,.2f} ${t['exit']:>9,.2f} "
                  f"{pc2}{t['pnl']:>+9.4f}{RESET} "
                  f"{Y}${t['fees']:>7.4f}{RESET} {t['reason']}")
        print()


# ── Master render ─────────────────────────────────────────────────

def render(orderbook, zones, momentum, signals, trader,
           mid_price, trades, action_log):
    clear()
    bids = orderbook.get("bids", [])
    asks = orderbook.get("asks", [])

    _header(mid_price, momentum)
    _orderbook(bids, asks, mid_price, zones)
    _live_trades(trades)
    _zones(zones, mid_price)
    _signals(signals)
    _position(trader.position, mid_price)
    _wallet(trader, mid_price, action_log)

    print(f"{C}{'─'*72}{RESET}")
    print(f"  {D}Updates every 2s — Ctrl+C to stop{RESET}")
