"""
Refactored reporting.py — Dash-based live/interactive candlestick viewer
Removes HTML export functionality. Provides a small Dash app that:
 - Loads OHLCV data from a CSV or a pandas DataFrame
 - Renders accurate candlesticks (correct body + wicks) using Plotly
 - Uses GPU-accelerated Scattergl for overlays (EMAs)
 - Loads only a window of candles at a time (server-side windowing)
 - Default window size: 500 (configurable), max 1000
 - Pan + scroll-zoom horizontally and vertically
 - On pan/zoom (relayout), server returns a new sliced window (keeps UI smooth)

Usage:
    1) Put your OHLCV CSV (with a datetime column named `timestamp` or `date`) somewhere.
    2) Run: python reporting.py --csv /path/to/ohlcv.csv --tscol timestamp --max_candles 1000
    3) Open http://127.0.0.1:8050 in your browser.

The CSV should contain columns: timestamp (or date), open, high, low, close, volume (volume optional).
Timestamps will be parsed as UTC if timezone info present.

This is intentionally standalone (no HTML exporting). It's designed to be dropped into your bot project and called
when you want to inspect price action for a symbol.
"""

import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State


# -------------------- Configuration --------------------
DEFAULT_MAX_CANDLES = 500  # default window size (visible / loaded at a time)
DEFAULT_MAX_ALLOWED = 1000  # absolute maximum to cap memory usage

# -------------------- Data loader / windower --------------------

def load_ohlcv(csv_path: str, timestamp_col: str = "timestamp") -> pd.DataFrame:
    """Load OHLCV CSV to a DataFrame indexed by timezone-aware datetime.

    Accepts common timestamp column names and returns df with datetime index and columns:
    open, high, low, close, volume (if present).
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)

    if timestamp_col not in df.columns:
        # try common alternatives
        for alt in ("date", "time", "datetime"):  # fallback guesses
            if alt in df.columns:
                timestamp_col = alt
                break

    df[timestamp_col] = pd.to_datetime(df[timestamp_col], utc=True, errors="coerce")
    df = df.dropna(subset=[timestamp_col])
    df = df.sort_values(timestamp_col).reset_index(drop=True)
    df.set_index(timestamp_col, inplace=True)

    # Ensure required columns exist
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            raise ValueError(f"Required column missing in CSV: '{col}'")

    # Keep only necessary columns
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep].copy()

    return df


def get_window(df: pd.DataFrame, start_ts=None, end_ts=None, center_ts=None, max_candles:int=DEFAULT_MAX_CANDLES) -> pd.DataFrame:
    """Return a capped window from df.

    If start_ts/end_ts provided, use them. Otherwise center on center_ts or return the last `max_candles` rows.
    The returned DataFrame is guaranteed to contain at most `max_candles` rows (most recent if reduction needed).
    """
    if start_ts is not None and end_ts is not None:
        # filter by range
        subset = df.loc[start_ts:end_ts]
    elif center_ts is not None:
        # center around a timestamp
        if not isinstance(center_ts, pd.Timestamp):
            center_ts = pd.to_datetime(center_ts, utc=True)
        if center_ts not in df.index:
            # find nearest index
            idx = df.index.get_indexer([center_ts], method="nearest")[0]
            center_ts = df.index[idx]
        center_pos = df.index.get_loc(center_ts)
        half = max_candles // 2
        start = max(0, center_pos - half)
        end = min(len(df), center_pos + half)
        subset = df.iloc[start:end]
    else:
        subset = df.iloc[-max_candles:]

    if len(subset) > max_candles:
        subset = subset.iloc[-max_candles:]

    return subset


# -------------------- Plot builder --------------------

def build_figure(df_win: pd.DataFrame, title: str = "Price Chart", show_volume: bool = True):
    """Construct a Plotly Figure for the provided windowed OHLCV dataframe."""
    up_color = "#26a69a"
    down_color = "#ef5350"

    fig = go.Figure()

    # Candlestick (accurate body + wick)
    fig.add_trace(go.Candlestick(
        x=df_win.index,
        open=df_win["open"], high=df_win["high"], low=df_win["low"], close=df_win["close"],
        increasing_line_color=up_color, decreasing_line_color=down_color,
        name="Candles",
        showlegend=False
    ))

    # EMAs (use Scattergl for smooth GPU-accelerated rendering)
    if len(df_win) >= 5:
        try:
            ema20 = df_win["close"].ewm(span=20, adjust=False).mean()
            ema50 = df_win["close"].ewm(span=50, adjust=False).mean()
            fig.add_trace(go.Scattergl(x=df_win.index, y=ema20, mode="lines", line=dict(width=1), name="EMA20"))
            fig.add_trace(go.Scattergl(x=df_win.index, y=ema50, mode="lines", line=dict(width=1), name="EMA50"))
        except Exception:
            pass

    # Volume as separate y-axis
    if show_volume and "volume" in df_win.columns:
        fig.add_trace(go.Bar(x=df_win.index, y=df_win["volume"], name="Volume",
                             marker=dict(color=np.where(df_win["close"] >= df_win["open"], up_color, down_color)),
                             yaxis="y2", opacity=0.6, showlegend=False))

    fig.update_layout(
        template="plotly_dark",
        title=title,
        xaxis=dict(type="date", rangeslider=dict(visible=False)),
        yaxis=dict(side="right", title="Price"),
        yaxis2=dict(overlaying="y", side="left", position=0.02, title="Volume", showgrid=False),
        hovermode="x unified",
        margin=dict(l=40, r=40, t=40, b=20),
        dragmode="pan",
    )

    # Make zooming with mousewheel enable scrollZoom
    config = {"scrollZoom": True}

    return fig, config


# -------------------- Dash App (server-side windowing) --------------------

def create_dash_app(df: pd.DataFrame, symbol: str = "SYMBOL", timeframe: str = "TF", max_candles: int = DEFAULT_MAX_CANDLES):
    app = Dash(__name__)
    server = app.server

    # keep the dataframe in server memory as a closure variable (fast slice operations)
    app.layout = html.Div([
        html.Div([html.H3(f"{symbol} — {timeframe}")], style={"textAlign": "center"}),
        dcc.Graph(id="price-graph", config={"displayModeBar": True, "scrollZoom": True}, style={"height": "80vh"}),
        # hidden store to pass simple state (not the entire df)
        dcc.Store(id="store-range", data={"max_candles": int(max_candles)}),
        html.Div(id="debug", style={"display": "none"})
    ])

    @app.callback(
        Output("price-graph", "figure"),
        Input("price-graph", "relayoutData"),
        State("store-range", "data")
    )
    def update_window(relayoutData, store_data):
        """When the chart is panned/zoomed, Plotly emits relayoutData with xaxis.range or xaxis.autorange.

        We parse that range and return a new figure built from a sliced window limited to max_candles.
        """
        max_c = min(int(store_data.get("max_candles", DEFAULT_MAX_CANDLES)), DEFAULT_MAX_ALLOWED)

        # default: last max_c candles
        start_ts = None
        end_ts = None

        if relayoutData and isinstance(relayoutData, dict):
            # several possible keys depending on user action
            # Example: 'xaxis.range[0]': '2025-10-01 00:00:00', 'xaxis.range[1]': '2025-10-05 00:00:00'
            if "xaxis.range[0]" in relayoutData and "xaxis.range[1]" in relayoutData:
                start_ts = pd.to_datetime(relayoutData["xaxis.range[0]"], utc=True, errors="coerce")
                end_ts = pd.to_datetime(relayoutData["xaxis.range[1]"], utc=True, errors="coerce")
            elif "xaxis.range" in relayoutData and isinstance(relayoutData["xaxis.range"], list):
                start_ts = pd.to_datetime(relayoutData["xaxis.range"][0], utc=True, errors="coerce")
                end_ts = pd.to_datetime(relayoutData["xaxis.range"][1], utc=True, errors="coerce")
            elif "xaxis.autorange" in relayoutData and relayoutData["xaxis.autorange"]:
                # default autorange -> show last window
                pass

        # If no explicit start/end, fallback to last window
        df_win = get_window(df, start_ts=start_ts, end_ts=end_ts, max_candles=max_c)

        fig, config = build_figure(df_win, title=f"{symbol} — {timeframe}")
        # attach config as attribute so Dash can pick it up (Dash Graph accepts figure only; config passed via component)
        # We'll return only figure; config is passed in layout via dcc.Graph config prop.
        return fig

    return app


# -------------------- CLI entrypoint --------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run the interactive OHLCV viewer (Dash).")
    ap.add_argument("--csv", required=True, help="Path to OHLCV CSV file")
    ap.add_argument("--tscol", default="timestamp", help="Timestamp column name in CSV (default: timestamp)")
    ap.add_argument("--symbol", default="SYMBOL", help="Symbol label for UI")
    ap.add_argument("--tf", default="1m", help="Timeframe label for UI")
    ap.add_argument("--max_candles", type=int, default=DEFAULT_MAX_CANDLES, help=f"Max candles to show/load (default {DEFAULT_MAX_CANDLES})")
    ap.add_argument("--host", default="127.0.0.1", help="Host for Dash server")
    ap.add_argument("--port", type=int, default=8050, help="Port for Dash server")

    args = ap.parse_args()

    if args.max_candles <= 0:
        raise ValueError("max_candles must be > 0")
    if args.max_candles > DEFAULT_MAX_ALLOWED:
        print(f"Max candles capped to {DEFAULT_MAX_ALLOWED} (requested {args.max_candles})")
        args.max_candles = DEFAULT_MAX_ALLOWED

    df_all = load_ohlcv(args.csv, timestamp_col=args.tscol)
    app = create_dash_app(df_all, symbol=args.symbol, timeframe=args.tf, max_candles=args.max_candles)
    app.run_server(host=args.host, port=args.port, debug=False)
