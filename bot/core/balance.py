"""
Balance, position sizing and leverage utilities for TRAMA Modular Bot
Author: Jarvis 2.0 (for Boss)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple

from bot.utils.constants import MIN_NOTIONAL, MAX_LEVERAGE_RISK, TAKER_FEE
from bot.core.logging_utils import log_warning, log_info

@dataclass
class PositionSizingResult:
    notional: float        # USD notional allocated to the position
    qty: float             # asset quantity (notional / price)
    entry_fee: float       # estimated entry fee in USD
    adjusted_notional: float  # notional after leverage risk clipping (if any)

def clip_notional_to_risk(balance: float, requested_notional: float) -> float:
    """
    Ensure notional does not exceed MAX_LEVERAGE_RISK * balance.
    Returns adjusted notional.
    """
    max_allowed = balance * MAX_LEVERAGE_RISK
    if requested_notional > max_allowed:
        log_warning(f"Requested notional ${requested_notional:.2f} exceeds max allowed ${max_allowed:.2f}. Clipping.")
        return max_allowed
    return requested_notional

def calculate_position_size(balance: float, position_pct: float, price: float, leverage: float) -> PositionSizingResult:
    """
    Calculate a position size given account balance, target position percent, price and leverage.

    Returns PositionSizingResult which includes:
      - notional: USD allocated (before clipping)
      - qty: asset quantity allocated (notional / price)
      - entry_fee: estimated taker fee at entry (qty * price * TAKER_FEE)
      - adjusted_notional: notional after clipping to MAX_LEVERAGE_RISK (if applied)

    Notes:
    - Does not subtract fees from notional; fees are returned separately in entry_fee.
    - Ensures notional >= MIN_NOTIONAL; if below, returns zeros.
    """
    if balance <= 0 or price <= 0:
        log_warning("Invalid balance or price when calculating position size.")
        return PositionSizingResult(0.0, 0.0, 0.0, 0.0)

    requested_notional = balance * position_pct
    adjusted_notional = clip_notional_to_risk(balance, requested_notional)

    if adjusted_notional < MIN_NOTIONAL:
        log_warning(f"Adjusted notional ${adjusted_notional:.2f} below MIN_NOTIONAL ${MIN_NOTIONAL:.2f}. Skipping position.")
        return PositionSizingResult(0.0, 0.0, 0.0, adjusted_notional)

    qty = adjusted_notional / price
    entry_fee = abs(qty * price * TAKER_FEE)

    return PositionSizingResult(requested_notional, qty, entry_fee, adjusted_notional)

def sufficient_balance_for_fees(balance: float, entry_fee: float) -> bool:
    """
    Quick check whether balance covers estimated entry fee.
    """
    if entry_fee >= balance:
        log_warning(f"Insufficient balance for fees: fee=${entry_fee:.4f} >= balance=${balance:.4f}")
        return False
    return True

def adjust_notional_for_margin(balance: float, desired_notional: float, leverage: float) -> Tuple[float, float]:
    """
    Given a desired notional and leverage, compute:
      - required_margin (USD)
      - adjusted_notional (clipped if required_margin > balance)

    required_margin = desired_notional / leverage

    If required_margin > balance, we clip desired_notional to balance * leverage.
    Returns (required_margin, adjusted_notional)
    """
    if leverage <= 0:
        log_warning("Non-positive leverage passed to adjust_notional_for_margin.")
        return 0.0, 0.0

    required_margin = desired_notional / leverage
    if required_margin > balance:
        adjusted_notional = balance * leverage
        log_warning(f"Required margin ${required_margin:.4f} exceeds balance ${balance:.4f}. Adjusting notional to ${adjusted_notional:.4f}")
        return balance, adjusted_notional
    return required_margin, desired_notional

# Lightweight examples for quick testing when run directly
if __name__ == "__main__":
    bal = 100.0
    price = 0.5
    pos_pct = 0.05
    lev = 10.0

    res = calculate_position_size(bal, pos_pct, price, lev)
    log_info(f"Requested notional: ${res.notional:.2f}")
    log_info(f"Adjusted notional: ${res.adjusted_notional:.2f}")
    log_info(f"Quantity @ {price}: {res.qty:.4f}")
    log_info(f"Estimated entry fee: ${res.entry_fee:.4f}")
