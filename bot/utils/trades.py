import statistics

def summarize_trades(trades, symbol, timeframe):
    """
    Create a simple readable trade summary for logging.
    Used by backtest.py to write human-readable logs.
    """
    if not trades:
        return f"No trades executed for {symbol} {timeframe}."

    lines = []
    lines.append(f"TRADE SUMMARY — {symbol} {timeframe}")
    lines.append("-" * 50)

    total = len(trades)
    wins = sum(1 for t in trades if t['pnl'] > 0)
    losses = total - wins
    avg_pnl = statistics.mean(t['pnl'] for t in trades)
    total_pnl = sum(t['pnl'] for t in trades)

    lines.append(f"Total Trades: {total}")
    lines.append(f"Wins: {wins} | Losses: {losses}")
    lines.append(f"Win Rate: {wins / total * 100:.2f}%")
    lines.append(f"Net PnL: {total_pnl:+.2f}")
    lines.append(f"Average PnL per trade: {avg_pnl:+.2f}")
    lines.append("-" * 50)

    # Detailed per-trade summary
    for i, t in enumerate(trades, 1):
        lines.append(
            f"{i:03d}: {t['side'].upper():5} | "
            f"Entry: {t['entry_price']:.5f} | Exit: {t['exit_price']:.5f} | "
            f"PnL: {t['pnl']:+.3f} | {t['entry_reason']} → {t['exit_reason']}"
        )

    return "\n".join(lines)
