import numpy as np

def compute_sharpe_ratio(pnls, risk_free_rate: float = 0.0):
    if not pnls:
        return 0.0
    arr = np.array(pnls)
    std = arr.std()
    return 0.0 if std == 0 else (arr.mean() - risk_free_rate) / std * np.sqrt(252)

def compute_max_drawdown(pnls):
    if not pnls:
        return 0.0
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    dd = equity - peak
    return abs(dd.min())

def compute_streak_stats(pnls):
    if not pnls:
        return dict(avg_consec_wins=0, avg_consec_losses=0,
                    max_consec_wins=0, max_consec_losses=0)
    wins, losses, streak = [], [], 0
    prev_win = pnls[0] > 0
    for p in pnls:
        win = p > 0
        if win == prev_win:
            streak += 1
        else:
            (wins if prev_win else losses).append(streak)
            streak = 1
        prev_win = win
    (wins if prev_win else losses).append(streak)
    return dict(
        avg_consec_wins=np.mean(wins) if wins else 0,
        avg_consec_losses=np.mean(losses) if losses else 0,
        max_consec_wins=max(wins) if wins else 0,
        max_consec_losses=max(losses) if losses else 0,
    )
