from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from colorama import Fore, Style

from bot.core.backtest import run_backtest_for
from bot.core.reporting import print_detailed_summary  # ✅ Removed write_html_report import
# If you want to open the live chart after backtest, import create_dash_app instead:
# from bot.core.reporting import create_dash_app, load_ohlcv

# ============= INLINE HELPER ============= #
def parse_date(date_str, default=None):
    """Parse YYYY-MM-DD to datetime (UTC)."""
    if not date_str:
        return default or datetime.now(timezone.utc)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return default or datetime.now(timezone.utc)

# ========================================= #

def parse_args():
    p = argparse.ArgumentParser(description="TRAMA Modular Backtester CLI")
    p.add_argument("--backtest", action="store_true", help="Run a backtest session")
    p.add_argument("--symbols", default="XRPUSDT", help="Comma-separated symbols")
    p.add_argument("--tfs", default="5m,15m,1h,4h", help="Comma-separated timeframes")
    p.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    p.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    p.add_argument("--start_balance", type=float, default=25.0)
    p.add_argument("--position_pct", type=float, default=0.05)
    p.add_argument("--leverage", type=float, default=10.0)
    p.add_argument("--debug", action="store_true", help="Enable debug output")
    p.add_argument("--show_chart", action="store_true", help="Launch interactive price viewer after backtest")  # ✅ optional
    return p.parse_args()


def main():
    args = parse_args()
    load_dotenv()

    if args.backtest:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        tfs = [t.strip() for t in args.tfs.split(",")]
        end = parse_date(args.end, datetime.now(timezone.utc))
        start = parse_date(args.start, end - timedelta(days=365))

        if end - start > timedelta(days=3 * 365):
            start = end - timedelta(days=3 * 365)
            print(f"{Fore.YELLOW}Requested period >3 years, clipped to 3 years.{Style.RESET_ALL}")

        print(f"{Fore.CYAN}Starting Backtest...{Style.RESET_ALL}")
        print(f"  Symbols: {', '.join(symbols)}")
        print(f"  Timeframes: {', '.join(tfs)}")
        print(f"  Period: {start.date()} → {end.date()}")
        print(f"  Start Balance: ${args.start_balance:.2f}")
        print(f"  Position %: {args.position_pct:.1%}")
        print(f"  Leverage: {args.leverage}x\n")

        results = run_backtest_for(
            symbols,
            tfs,
            start,
            end,
            start_balance=args.start_balance,
            position_pct=args.position_pct,
            leverage=args.leverage,
            debug=args.debug,
        )

        if results:
            print_detailed_summary(results)  # ✅ Replaced HTML export with summary printout
            print(f"\n{Fore.GREEN}Backtest completed successfully!{Style.RESET_ALL}")
            print(f"  ✓ Reports displayed in console (no HTML export).")

            # Optional live chart after backtest (if you want):
            if args.show_chart:
                try:
                    from bot.core.reporting import create_dash_app, load_ohlcv
                    import os
                    latest_csv = os.path.join("data", f"{symbols[0]}_{tfs[0]}.csv")
                    if os.path.exists(latest_csv):
                        df = load_ohlcv(latest_csv)
                        app = create_dash_app(df, symbol=symbols[0], timeframe=tfs[0])
                        app.run_server(debug=False)
                    else:
                        print(f"{Fore.YELLOW}No CSV data found for {symbols[0]} to display chart.{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}Chart display failed: {e}{Style.RESET_ALL}")
        else:
            print(f"{Fore.RED}No results generated. Please verify your inputs.{Style.RESET_ALL}")


if __name__ == "__main__":
    main()
