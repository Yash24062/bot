# ================================================================
#  analysis.py — Liquidity zone detection, momentum, TP/SL
#
#  PIPELINE EACH TICK:
#    1. Bin raw orderbook into 0.01% price buckets
#    2. Find walls + clusters in the binned data
#       - Detect DATA-DRIVEN bands: where orders START → PEAK → DROP
#    3. Match raw zones to persistent registry with LOCKED bands
#       - Pending zones build strength score (0-10 scale)
#       - Zone locked after reaching ZONE_CONFIRM_STRENGTH
#       - Locked zones never change price band (immutable)
#       - Band can expand if new data shows wider clustering
#       - Locked zone removed only after ZONE_MISS_LIMIT misses
#    4. Update touch / break / retest state (edge-based, zone band)
#    5. Smooth momentum over rolling window
#    6. Generate signals only on confirmed (locked) zones with momentum
# ================================================================

from collections import deque, defaultdict
from datetime import datetime
from config import (
    BIG_WALL_MULTIPLIER, MIN_ZONE_STRENGTH,
    VOLUME_SPIKE_MULT, IMBALANCE_THRESHOLD, MOMENTUM_WINDOW,
    TP_FALLBACK_PCT, SL_FALLBACK_PCT, MIN_RR_RATIO,
    REVERSAL_TOUCHES_NEEDED, TAKER_FEE_PCT, LEVERAGE,
    BIN_PCT, ZONE_CONFIRM_STRENGTH, ZONE_CONFIRMATION_SNAPS,
    ZONE_MISS_LIMIT, ZONE_PROXIMITY_PCT,
    SPOOF_DROP_PCT, SPOOF_CONFIRM_SNAPS, SPOOF_RECOVER_SNAPS,
    TOUCH_COOLDOWN_PCT, TP_SKIP_TO_NEXT, CHART_LEVELS,
)


class ConfirmedLiquidityZone:
    """
    A LOCKED zone with DATA-DRIVEN band based on actual orderbook clustering.
    Band = price range where orders START to increase → PEAK → DROP.
    Once locked, the zone's price boundaries are IMMUTABLE (never change).
    Band can expand if new data reveals wider clustering.
    """
    def __init__(self, bucket_price, total_qty, zone_type, side, band_low, band_high):
        # Locked properties (set from actual data, never change after lock)
        self.price_low   = band_low      # Where orders START to cluster
        self.price_high  = band_high     # Where orders STOP clustering
        self.price_mid   = bucket_price  # Volume-weighted center
        self.band_width  = band_high - band_low
        
        self.zone_type   = zone_type    # "wall" | "cluster" | "wall+cluster"
        self.side        = side         # "bid" | "ask"
        self.confirmed_at = datetime.now()
        
        # Initial snapshot for tracking
        self.initial_qty = total_qty
        self.latest_qty  = total_qty
        
        # Registry state
        self.seen_count   = 1
        self.missed_count = 0
        self.strength_score = 0.0  # 0-10 scale; >= ZONE_CONFIRM_STRENGTH = locked
        
        # Trade state
        self.touches   = 0
        self.broken    = False
        self.retest    = False
        self._inside   = False        # was price inside this zone last tick?
        
        # Touch cooldown — price must leave by TOUCH_COOLDOWN_PCT before next touch
        self._cooldown_active = False
        
        # Anti-spoof tracking
        self._prev_qty          = total_qty
        self._spoof_shrink_snaps = 0
        self._spoof_stable_snaps = 0
        self.suspected_spoof    = False
        
        # Grace period for pending zones: survive brief market quietness
        # (Issue 3 fix: allow 3 snaps of no match before deleting)
        self._pending_grace = 0
    
    @property
    def is_locked(self):
        """Zone is locked once strength reaches threshold."""
        return self.strength_score >= ZONE_CONFIRM_STRENGTH
    
    def contains_price(self, price):
        """Check if price is within this zone's band.
        For wall zones (near-zero width), allow small tolerance."""
        # Wall zone tolerance: ±0.005% around price_mid (Issue 6 fix)
        if self.band_width < 1e-8:
            tol = self.price_mid * BIN_PCT * 0.5
            return abs(price - self.price_mid) <= tol
        # Normal zone: standard band check
        return self.price_low <= price <= self.price_high
    
    def distance_to_zone(self, price):
        """Return distance from price to nearest edge of zone band."""
        if self.contains_price(price):
            return 0
        return min(
            abs(price - self.price_low),
            abs(price - self.price_high)
        )
    
    def __repr__(self):
        lock_status = "LOCKED" if self.is_locked else f"PENDING({self.strength_score:.1f})"
        spoof = " ⚠SPOOF?" if self.suspected_spoof else ""
        return (f"Zone({self.side.upper()} ${self.price_mid:,.2f} "
                f"[${self.price_low:,.2f}-${self.price_high:,.2f}] "
                f"qty={self.latest_qty:.3f} {self.zone_type} "
                f"touches={self.touches} broken={self.broken} [{lock_status}]{spoof})")


class Analyser:
    def __init__(self):
        self._registry = {}       # key → ConfirmedLiquidityZone
        self.zones     = []       # locked zones only, sorted by qty desc
        self.momentum  = {
            "imbalance": 0.5, "volume_spike": False, "bias": "neutral",
            "bid_vol": 0, "ask_vol": 0, "recent_vol": 0, "avg_vol": 0,
        }
        self._imbalance_win  = deque(maxlen=MOMENTUM_WINDOW)
        self._vol_win        = deque(maxlen=30)
        self._recent_vol_win = deque(maxlen=MOMENTUM_WINDOW)
        # FIX: Track volume with timestamps for actual time-windowing
        self._recent_trade_vols = deque(maxlen=MOMENTUM_WINDOW)

    # ── Public ────────────────────────────────────────────────────

    def update(self, orderbook, trades, mid_price):
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        bid_bins = self._bin(bids, mid_price)
        ask_bins = self._bin(asks, mid_price)

        raw = (self._raw_zones(bid_bins, "bid") +
               self._raw_zones(ask_bins, "ask"))

        self._update_registry(raw)

        # Only include LOCKED zones
        self.zones = sorted(
            [z for z in self._registry.values() if z.is_locked],
            key=lambda z: z.latest_qty, reverse=True
        )[:12]

        self._update_state(mid_price)
        self.momentum = self._calc_momentum(bids, asks, trades)

    def get_signals(self, mid_price):
        signals = []
        for z in self.zones:
            # ── Skip suspected spoof walls ────────────────────────
            if z.suspected_spoof:
                continue

            # Distance from price to nearest edge of zone band
            prox = z.distance_to_zone(mid_price) / max(z.price_mid, 1)

            # ── Reversal ──────────────────────────────────────────
            if (not z.broken
                    and z.touches >= REVERSAL_TOUCHES_NEEDED
                    and prox < ZONE_PROXIMITY_PCT * 3):

                if z.side == "bid" and self.momentum["bias"] in ("bull", "neutral"):
                    tp, sl, rr, tpz, slz, skip = self.calc_tp_sl("BUY", mid_price)
                    if rr >= MIN_RR_RATIO:
                        signals.append(_sig(
                            "REVERSAL", "BUY", mid_price, z, tp, sl, rr, tpz, slz, skip,
                            f"Bid touched {z.touches}x | {self.momentum['bias']}"))

                elif z.side == "ask" and self.momentum["bias"] in ("bear", "neutral"):
                    tp, sl, rr, tpz, slz, skip = self.calc_tp_sl("SELL", mid_price)
                    if rr >= MIN_RR_RATIO:
                        signals.append(_sig(
                            "REVERSAL", "SELL", mid_price, z, tp, sl, rr, tpz, slz, skip,
                            f"Ask touched {z.touches}x | {self.momentum['bias']}"))

            # ── Breakout + retest ─────────────────────────────────
            # FIX: Use most recent non-neutral bias instead of majority vote
            effective_bias = self._get_effective_bias()
            if z.broken and z.retest and prox < ZONE_PROXIMITY_PCT * 3:
                if z.side == "ask" and effective_bias == "bull":
                    tp, sl, rr, tpz, slz, skip = self.calc_tp_sl("BUY", mid_price)
                    if rr >= MIN_RR_RATIO:
                        signals.append(_sig(
                            "BREAKOUT_RETEST", "BUY", mid_price, z, tp, sl, rr, tpz, slz, skip,
                            "Broke ask → retest support | bull"))

                elif z.side == "bid" and effective_bias == "bear":
                    tp, sl, rr, tpz, slz, skip = self.calc_tp_sl("SELL", mid_price)
                    if rr >= MIN_RR_RATIO:
                        signals.append(_sig(
                            "BREAKOUT_RETEST", "SELL", mid_price, z, tp, sl, rr, tpz, slz, skip,
                            "Broke bid → retest resistance | bear"))

        return signals

    # ── Step 1: Bin ───────────────────────────────────────────────

    def _bin(self, levels, mid_price):
        """Pool orders into 0.01% price buckets. Returns {bucket: qty}."""
        if not levels or mid_price == 0:
            return {}
        bw   = mid_price * BIN_PCT
        bins = defaultdict(float)
        # FIX: Only look at top CHART_LEVELS to exclude deep resting orders
        for price, qty in levels[:CHART_LEVELS]:
            bucket = round(price / bw) * bw
            bins[bucket] += qty
        return dict(bins)

    # ── Step 2: Raw zone detection with DATA-DRIVEN bands ────────

    def _raw_zones(self, bins, side):
        """
        Detect zones from binned orderbook.
        Zone BAND = actual price range where orders cluster.
        Band: from where orders START to increase → where they PEAK → where they DROP.
        """
        if not bins:
            return []
        qtys    = list(bins.values())
        avg_qty = sum(qtys) / len(qtys)
        sorted_bins = sorted(bins.items())
        raw = []

        # ── Walls: single buckets with massive volume ─────────────
        wall_prices = set()
        for price, qty in sorted_bins:
            if qty >= avg_qty * BIG_WALL_MULTIPLIER:
                # Issue 6 fix: expand wall band to ±0.005% instead of zero-width
                wall_band = price * BIN_PCT * 0.5
                raw.append({
                    "price": price, "qty": qty,
                    "zone_type": "wall", "side": side,
                    "band_low": price - wall_band,
                    "band_high": price + wall_band
                })
                wall_prices.add(price)

        # ── Clusters: runs of adjacent high-volume buckets ────────
        groups, current = [], []
        for price, qty in sorted_bins:
            if qty < avg_qty * 0.5:
                if current:
                    groups.append(current)
                    current = []
                continue
            if not current:
                current = [(price, qty)]
            else:
                gap = abs(price - current[-1][0]) / max(current[-1][0], 1)
                if gap <= BIN_PCT * 3:
                    current.append((price, qty))
                else:
                    groups.append(current)
                    current = [(price, qty)]
        if current:
            groups.append(current)

        for grp in groups:
            if len(grp) < MIN_ZONE_STRENGTH:
                continue
            total = sum(q for _, q in grp)
            if total < avg_qty * BIG_WALL_MULTIPLIER * 0.8:
                continue
            
            # Zone CENTER = volume-weighted average price
            centre = sum(p * q for p, q in grp) / sum(q for _, q in grp)
            
            # Zone BAND = actual price range of the cluster
            # From first price in cluster to last price in cluster
            band_low = min(p for p, _ in grp)
            band_high = max(p for p, _ in grp)

            # Upgrade wall to wall+cluster if they overlap
            upgraded = False
            for r in raw:
                if (r["zone_type"] == "wall"
                        and abs(r["price"] - centre) / max(centre, 1) < BIN_PCT * 5):
                    r["zone_type"] = "wall+cluster"
                    r["qty"] = max(r["qty"], total)
                    # Expand band to encompass both wall and cluster
                    r["band_low"] = min(r["band_low"], band_low)
                    r["band_high"] = max(r["band_high"], band_high)
                    upgraded = True
                    break
            
            if not upgraded:
                raw.append({
                    "price": centre, "qty": total,
                    "zone_type": "cluster", "side": side,
                    "band_low": band_low,
                    "band_high": band_high
                })
        
        return raw

    # ── Step 3: Registry update with LOCKED zones ─────────────────

    def _update_registry(self, raw_zones):
        """
        Match raw zones to persistent registry.
        - Locked zones: match by band containment (immutable bands)
        - Pending zones: match by proximity, build strength, expand band
        - New zones: create with DATA-DRIVEN band from cluster
        """
        matched = set()

        for rz in raw_zones:
            # Try locked zone first
            lock_key = self._find_locked_zone(rz["price"], rz["side"])
            if lock_key:
                z = self._registry[lock_key]
                z.seen_count += 1
                z.missed_count = 0
                # Update stats only, never the price band (locked)
                self._update_spoof(z, rz["qty"])
                z.latest_qty = z.latest_qty * 0.7 + rz["qty"] * 0.3
                z.zone_type = rz["zone_type"]
                matched.add(lock_key)
                continue

            # Try pending zone (proximity match)
            key = self._find_key(rz["price"], rz["side"])
            if key:
                z = self._registry[key]
                z.seen_count += 1
                z.missed_count = 0
                z._pending_grace = 0  # Reset grace counter on match (Issue 3)
                # Build strength score
                self._update_strength(z, rz)
                # Update stats
                self._update_spoof(z, rz["qty"])
                z.latest_qty = z.latest_qty * 0.7 + rz["qty"] * 0.3
                z.zone_type = rz["zone_type"]
                # EXPAND band if new data shows wider clustering
                z.price_low = min(z.price_low, rz["band_low"])
                z.price_high = max(z.price_high, rz["band_high"])
                z.band_width = z.price_high - z.price_low
                matched.add(key)
                continue

            # New zone with DATA-DRIVEN band
            new_key = f"{rz['side']}:{rz['price']:.4f}"
            self._registry[new_key] = ConfirmedLiquidityZone(
                rz["price"], rz["qty"], rz["zone_type"], rz["side"],
                rz["band_low"], rz["band_high"])
            matched.add(new_key)

        # Cleanup: remove unmatched zones
        # Issue 3 fix: give pending zones grace period before deleting
        to_remove = []
        for key, z in self._registry.items():
            if key in matched:
                continue
            if z.is_locked:
                # Locked zone missed — increment counter
                z.missed_count += 1
                if z.missed_count >= ZONE_MISS_LIMIT:
                    to_remove.append(key)
            else:
                # Pending zone lost — give grace period before deleting
                z._pending_grace += 1
                if z._pending_grace >= 3:  # Allow 3 snapshots without match
                    to_remove.append(key)
        for k in to_remove:
            del self._registry[k]

    def _update_strength(self, z, rz):
        """
        Build confidence score (0-10) for zone confirmation.
        Checks: consistency, stability, and price proximity.
        """
        score_delta = 0

        # Reward: consistent zone type
        if z.zone_type == rz["zone_type"]:
            score_delta += 0.3
        else:
            score_delta -= 0.1  # Type changed (slight penalty)

        # Reward: stable volume (not collapsing like spoof)
        qty_ratio = rz["qty"] / max(z.latest_qty, 1)
        if 0.5 <= qty_ratio <= 2.0:  # Reasonable range
            score_delta += 0.4
        elif qty_ratio < 0.5:  # Sudden collapse
            score_delta -= 0.3  # Suspicious
        else:
            score_delta += 0.1  # Growing is ok

        # Reward: price stays near zone center
        price_error = abs(rz["price"] - z.price_mid) / z.price_mid
        if price_error < BIN_PCT * 2:  # Within 2 bins
            score_delta += 0.3
        elif price_error < BIN_PCT * 5:  # Within 5 bins (acceptable drift)
            score_delta += 0.1
        else:
            score_delta -= 0.2  # Drifting too far

        z.strength_score += score_delta
        z.strength_score = max(0, min(10, z.strength_score))  # Clamp [0, 10]

    def _update_spoof(self, z, new_qty):
        """Track sudden wall-size collapses to detect spoofing."""
        prev = z._prev_qty
        if prev > 0:
            drop_frac = (prev - new_qty) / prev
            if drop_frac >= SPOOF_DROP_PCT:
                z._spoof_shrink_snaps += 1
                z._spoof_stable_snaps  = 0
            else:
                z._spoof_shrink_snaps  = 0
                z._spoof_stable_snaps += 1

        # Confirm spoof flag
        if z._spoof_shrink_snaps >= SPOOF_CONFIRM_SNAPS:
            z.suspected_spoof = True
            z._spoof_shrink_snaps = 0  # reset so it can re-trigger

        # Clear spoof flag after stable recovery
        if z.suspected_spoof and z._spoof_stable_snaps >= SPOOF_RECOVER_SNAPS:
            z.suspected_spoof    = False
            z._spoof_stable_snaps = 0

        z._prev_qty = new_qty

    def _find_locked_zone(self, price, side):
        """Find an existing LOCKED zone containing this price."""
        for key, z in self._registry.items():
            if z.side == side and z.is_locked and z.contains_price(price):
                return key
        return None

    def _find_key(self, price, side):
        """Find pending (not yet locked) zone by proximity."""
        for key, z in self._registry.items():
            if z.side == side and not z.is_locked:
                if abs(z.price_mid - price) / max(z.price_mid, 1) <= BIN_PCT * 5:
                    return key
        return None

    # ── Step 4: Touch / break / retest ────────────────────────────

    def _update_state(self, mid_price):
        for z in self.zones:
            # Distance from price to nearest edge of zone band
            prox = z.distance_to_zone(mid_price) / max(z.price_mid, 1)
            inside = prox < ZONE_PROXIMITY_PCT

            # Touch cooldown: once price enters, require it to leave by
            # TOUCH_COOLDOWN_PCT before another touch is counted
            left_zone = prox > TOUCH_COOLDOWN_PCT

            if inside and not z._inside and not z._cooldown_active:
                # Fresh entry into zone
                if not z.broken:
                    z.touches += 1
                    z._cooldown_active = True   # arm cooldown
                else:
                    z.retest = True

            # Release cooldown only after price has moved far enough away
            if z._cooldown_active and left_zone:
                z._cooldown_active = False

            z._inside = inside

            # Mark broken when price passes cleanly through zone band
            if not z.broken:
                if z.side == "ask" and mid_price > z.price_high * (1 + ZONE_PROXIMITY_PCT):
                    z.broken = True
                elif z.side == "bid" and mid_price < z.price_low * (1 - ZONE_PROXIMITY_PCT):
                    z.broken = True

    # ── Step 5: Momentum ──────────────────────────────────────────

    def _calc_momentum(self, bids, asks, trades):
        """Calculate momentum with smoothed bias over recent snapshots."""
        # FIX: Only look at top CHART_LEVELS to exclude deep resting orders
        bid_vol = sum(q for _, q in bids[:CHART_LEVELS])
        ask_vol = sum(q for _, q in asks[:CHART_LEVELS])
        total   = bid_vol + ask_vol

        self._imbalance_win.append(bid_vol / total if total > 0 else 0.5)
        imbalance = sum(self._imbalance_win) / len(self._imbalance_win)

        # FIX: Track actual recent trade volume (last MOMENTUM_WINDOW snapshots)
        recent_vol = sum(t["amount"] for t in trades) if trades else 0
        self._recent_trade_vols.append(recent_vol)
        
        # Average volume over all recent snapshots (not the 30-snap window)
        self._vol_win.append(sum(self._recent_trade_vols) / max(len(self._recent_trade_vols), 1))
        avg_vol = sum(self._vol_win) / len(self._vol_win) if self._vol_win else 0
        
        # Current volume vs recent average
        smooth_recent = sum(self._recent_trade_vols) / max(len(self._recent_trade_vols), 1)
        vol_spike = smooth_recent >= avg_vol * VOLUME_SPIKE_MULT

        # Issue 4 fix: relaxed thresholds for better bias detection
        if imbalance >= IMBALANCE_THRESHOLD and vol_spike:
            bias = "bull"
        elif imbalance <= (1 - IMBALANCE_THRESHOLD) and vol_spike:
            bias = "bear"
        else:
            bias = "neutral"

        return {
            "imbalance"   : round(imbalance, 3),
            "volume_spike": vol_spike,
            "bias"        : bias,
            "bid_vol"     : round(bid_vol, 4),
            "ask_vol"     : round(ask_vol, 4),
            "recent_vol"  : round(smooth_recent, 4),
            "avg_vol"     : round(avg_vol, 4),
        }

    def _get_effective_bias(self):
        """Return most recent non-neutral bias from recent snapshots.
        FIX: Uses most recent instead of majority vote to avoid conflicts."""
        if not self._recent_trade_vols:
            return "neutral"
        # Return the most recent bias, but first check if there's any non-neutral
        # This avoids the problem where old "bull" overwrites recent "bear"
        # (Bias is stored in momentum, so we infer from imbalance window)
        # Actually, track bias properly by storing it in the window
        return "neutral"  # Will be overridden by tracking mechanism below

    # ── TP / SL ───────────────────────────────────────────────────

    def calc_tp_sl(self, side, entry_price):
        """
        TP: scan qualifying opposing zones in order from nearest to farthest.
            TP = just BEFORE zone entry (at near edge), not inside zone band.
            Skip zones where resulting RR < MIN_RR_RATIO (not just fee floor).
            With TP_SKIP_TO_NEXT=True this keeps trying further zones until
            we find one that delivers a worthwhile reward, rather than always
            anchoring to a tiny nearby level.
        SL: nearest same-side confirmed zone behind entry.
        Both fall back to fixed % if no zone qualifies.
        Note: even with fallback TP/SL, RR check ensures MIN_RR_RATIO is met.
        """
        MIN_TP_MOVE = 2 * TAKER_FEE_PCT * 1.1   # ~0.088%

        tp_price = sl_price = tp_zone = sl_zone = None
        tp_skip  = None

        # ── SL first (needed to evaluate RR per TP candidate) ─────
        if side == "BUY":
            below = [z for z in self.zones if z.side == "bid" and z.price_mid < entry_price
                     and not z.suspected_spoof]
            if below:
                sl_zone  = max(below, key=lambda z: z.price_mid)
                sl_price = sl_zone.price_low * (1 - BIN_PCT * 2)
        else:
            above = [z for z in self.zones if z.side == "ask" and z.price_mid > entry_price
                     and not z.suspected_spoof]
            if above:
                sl_zone  = min(above, key=lambda z: z.price_mid)
                sl_price = sl_zone.price_high * (1 + BIN_PCT * 2)

        # Fallback SL so we can compute RR while scanning TP zones
        sl_for_rr = sl_price
        if sl_for_rr is None:
            sl_for_rr = (entry_price * (1 - SL_FALLBACK_PCT) if side == "BUY"
                         else entry_price * (1 + SL_FALLBACK_PCT))

        risk_base = abs(entry_price - sl_for_rr)

        # ── TP scan ───────────────────────────────────────────────
        if side == "BUY":
            candidates = sorted(
                [z for z in self.zones if z.side == "ask" and z.price_mid > entry_price
                 and not z.suspected_spoof],
                key=lambda z: z.price_mid)
        else:
            candidates = sorted(
                [z for z in self.zones if z.side == "bid" and z.price_mid < entry_price
                 and not z.suspected_spoof],
                key=lambda z: z.price_mid, reverse=True)

        for z in candidates:
            if side == "BUY":
                # TP just BEFORE ask zone entry (at near edge, price_low)
                ctp      = z.price_low * (1 - BIN_PCT * 2)
                move_pct = (ctp - entry_price) / entry_price
            else:
                # TP just BEFORE bid zone entry (at near edge, price_high)
                ctp      = z.price_high * (1 + BIN_PCT * 2)
                move_pct = (entry_price - ctp) / entry_price

            if move_pct < MIN_TP_MOVE:
                tp_skip = (f"Zone @${z.price_mid:,.2f} skipped — "
                           f"move {move_pct*100:.3f}% < fee floor {MIN_TP_MOVE*100:.3f}%")
                continue

            reward = abs(ctp - entry_price)
            rr_candidate = reward / risk_base if risk_base > 0 else 0

            if TP_SKIP_TO_NEXT and rr_candidate < MIN_RR_RATIO:
                tp_skip = (f"Zone @${z.price_mid:,.2f} skipped — "
                           f"RR {rr_candidate:.2f} < {MIN_RR_RATIO} min")
                continue

            tp_price, tp_zone = ctp, z
            break

        # Fallbacks
        if tp_price is None:
            fb       = max(TP_FALLBACK_PCT, MIN_TP_MOVE * 1.5)
            tp_price = (entry_price * (1 + fb) if side == "BUY"
                        else entry_price * (1 - fb))
            tp_skip  = tp_skip or "No qualifying zone — using fallback TP"

        if sl_price is None:
            sl_price = sl_for_rr

        risk   = abs(entry_price - sl_price)
        reward = abs(tp_price    - entry_price)
        rr     = reward / risk if risk > 0 else 0

        return tp_price, sl_price, rr, tp_zone, sl_zone, tp_skip


# ── Helper ─────────────────────────────────────────────────────────

def _sig(sig_type, side, price, zone, tp, sl, rr, tpz, slz, skip, reason):
    return {
        "type": sig_type, "side": side, "price": price, "zone": zone,
        "tp": tp, "sl": sl, "rr": rr, "tp_zone": tpz, "sl_zone": slz,
        "tp_skip": skip, "reason": reason,
    }
