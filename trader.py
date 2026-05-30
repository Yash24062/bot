# ================================================================
#  trader.py — Paper trading with leverage + fee tracking
#
#  LEVERAGE MECHANICS:
#    Margin $10 × 10x = $100 notional position
#    PnL calculated on notional — fees too
#    Liquidation if loss >= margin (price moves 10% against you)
#
#  FEE MECHANICS:
#    Entry fee = notional × 0.04%
#    Exit fee  = notional × 0.04%
#    Both deducted from PnL automatically
# ================================================================

from datetime import datetime
from config import TRADE_SIZE_USDT, STARTING_BALANCE, LEVERAGE, TAKER_FEE_PCT, ALLOW_REENTRY


class Position:
    def __init__(self, side, entry_price, margin, tp, sl,
                 signal_type, reason, tp_zone=None, sl_zone=None):
        self.side        = side
        self.entry_price = entry_price
        self.margin      = margin
        self.notional    = margin * LEVERAGE
        self.qty         = self.notional / entry_price
        self.tp          = tp
        self.sl          = sl
        self.tp_zone     = tp_zone
        self.sl_zone     = sl_zone
        self.signal_type = signal_type
        self.reason      = reason
        self.open_time   = datetime.now()
        self.entry_fee   = self.notional * TAKER_FEE_PCT

    def unrealised_pnl(self, price):
        raw      = (price - self.entry_price) * self.qty if self.side == "BUY" \
                   else (self.entry_price - price) * self.qty
        exit_fee = price * self.qty * TAKER_FEE_PCT
        return raw - self.entry_fee - exit_fee

    def net_pnl(self, exit_price):
        raw      = (exit_price - self.entry_price) * self.qty if self.side == "BUY" \
                   else (self.entry_price - exit_price) * self.qty
        exit_fee = exit_price * self.qty * TAKER_FEE_PCT
        return raw - self.entry_fee - exit_fee

    def liquidation_price(self):
        return (self.entry_price * (1 - 1 / LEVERAGE) if self.side == "BUY"
                else self.entry_price * (1 + 1 / LEVERAGE))

    def should_stop(self, price):
        return price <= self.sl if self.side == "BUY" else price >= self.sl

    def should_tp(self, price):
        return price >= self.tp if self.side == "BUY" else price <= self.tp

    def should_liquidate(self, price):
        liq = self.liquidation_price()
        return price <= liq if self.side == "BUY" else price >= liq


class Trader:
    def __init__(self):
        self.balance    = STARTING_BALANCE
        self.position   = None
        self.trade_log  = []
        self.wins       = 0
        self.losses     = 0
        self.total_fees = 0.0

        # Re-entry tracking
        self._last_stop_zone  = None   # zone that triggered the last SL
        self._last_stop_side  = None   # BUY / SELL of the stopped trade
        self._reentry_used    = False  # one re-entry per stop event

    def evaluate(self, signals, mid_price):
        action_log = []

        if self.position:
            pos = self.position
            if pos.should_liquidate(mid_price):
                closed = self._close(mid_price, "LIQUIDATED")
                self._last_stop_zone  = None
                self._last_stop_side  = None
                self._reentry_used    = True   # no re-entry after liquidation
                action_log.append(
                    f"💥 LIQUIDATED | Lost ${pos.margin:.2f} margin | Fees ${closed['fees']:.4f}")
            elif pos.should_stop(mid_price):
                closed = self._close(mid_price, "STOP LOSS")
                # Remember zone + side for potential re-entry
                self._last_stop_zone  = getattr(pos, 'sl_zone', None)
                self._last_stop_side  = pos.side
                self._reentry_used    = False
                action_log.append(
                    f"🛑 STOP LOSS | PnL {closed['pnl']:+.4f} | Fees ${closed['fees']:.4f}")
            elif pos.should_tp(mid_price):
                closed = self._close(mid_price, "TAKE PROFIT")
                self._last_stop_zone  = None
                self._last_stop_side  = None
                self._reentry_used    = True   # no re-entry after TP; clean exit
                action_log.append(
                    f"✅ TAKE PROFIT | PnL {closed['pnl']:+.4f} | Fees ${closed['fees']:.4f}")

        if not self.position and signals:
            # ── Normal entry ──────────────────────────────────────
            sig = signals[0]
            entered = False

            # ── Re-entry check ────────────────────────────────────
            # Allow one re-entry if: stopped out recently, zone is still
            # intact (not broken, not a spoof), and signal is same direction.
            if (ALLOW_REENTRY
                    and not self._reentry_used
                    and self._last_stop_zone is not None
                    and self._last_stop_side == sig["side"]):
                z = self._last_stop_zone
                zone_ok = (not z.broken and not getattr(z, 'suspected_spoof', False))
                if zone_ok:
                    if self._open(sig, mid_price):
                        self._reentry_used = True
                        entered = True
                        action_log.append(
                            f"🔁 RE-ENTRY {sig['side']} @ ${mid_price:,.2f} | "
                            f"Zone intact | TP ${sig['tp']:,.2f} SL ${sig['sl']:,.2f} | "
                            f"RR {sig['rr']:.2f}")

            if not entered and self._open(sig, mid_price):
                # Reset re-entry state on any new fresh trade
                self._last_stop_zone = None
                self._last_stop_side = None
                self._reentry_used   = True
                action_log.append(
                    f"📈 {sig['side']} @ ${mid_price:,.2f} | "
                    f"TP ${sig['tp']:,.2f} SL ${sig['sl']:,.2f} | "
                    f"RR {sig['rr']:.2f} | {sig['type']}")

        return action_log

    def _open(self, signal, price):
        if price <= 0 or self.balance < TRADE_SIZE_USDT:
            return False
        margin        = TRADE_SIZE_USDT
        self.balance -= margin
        self.total_fees += margin * LEVERAGE * TAKER_FEE_PCT
        self.position = Position(
            side=signal["side"], entry_price=price, margin=margin,
            tp=signal["tp"], sl=signal["sl"],
            signal_type=signal["type"], reason=signal["reason"],
            tp_zone=signal.get("tp_zone"), sl_zone=signal.get("sl_zone"),
        )
        return True

    def _close(self, price, reason):
        pos      = self.position
        pnl      = pos.net_pnl(price)
        exit_fee = price * pos.qty * TAKER_FEE_PCT
        self.balance    += pos.margin + pnl
        self.total_fees += exit_fee
        if pnl >= 0:
            self.wins += 1
        else:
            self.losses += 1
        record = {
            "side": pos.side, "entry": pos.entry_price, "exit": price,
            "margin": pos.margin, "notional": pos.notional, "qty": pos.qty,
            "pnl": pnl, "fees": pos.entry_fee + exit_fee,
            "reason": reason, "type": pos.signal_type,
            "duration": str(datetime.now() - pos.open_time).split(".")[0],
            "time": datetime.now().strftime("%H:%M:%S"),
            "tp": pos.tp, "sl": pos.sl,
        }
        self.trade_log.append(record)
        self.position = None
        return record

    def total_value(self, mid_price):
        val = self.balance
        if self.position:
            val += self.position.unrealised_pnl(mid_price)
        return val

    def summary(self):
        total = self.wins + self.losses
        return {
            "balance"   : self.balance,
            "trades"    : total,
            "wins"      : self.wins,
            "losses"    : self.losses,
            "win_rate"  : (self.wins / total * 100) if total > 0 else 0,
            "total_fees": self.total_fees,
        }
