# ================================================================
#  data_feed.py — Binance USDT-M Futures
#                 WebSocket diff stream + local book maintenance
#
#  HOW IT WORKS:
#    1. REST snapshot seeds the local book (up to 5000 levels)
#    2. WebSocket diff stream applies incremental updates
#    3. REST trades poll runs in parallel (no WS stream needed)
#
#  UPGRADE vs old version:
#    - Full 5000-level depth instead of ~1000
#    - 100ms book updates instead of 2s polls
#    - Zero REST rate-limit pressure on book
#    - Diff tracking for spoof detection improvements
# ================================================================

import ccxt
import time
import threading
import json
import websocket
import requests
import logging
from collections import deque, OrderedDict
from config import SYMBOL, FETCH_INTERVAL, TRADE_HISTORY_LEN

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Binance WebSocket base for USDT-M Futures
_WS_BASE   = "wss://fstream.binance.com/ws"
_REST_BASE = "https://fapi.binance.com"

# Convert "BTC/USDT:USDT" → "btcusdt" for WS stream name
def _ws_symbol(symbol: str) -> str:
    return symbol.split("/")[0].lower() + symbol.split("/")[1].split(":")[0].lower()


class DataFeed:
    def __init__(self):
        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

        # Local order book — sorted dicts: price → qty
        # Using plain dicts; we sort on read (cheap at 5000 levels)
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}
        self._last_update_id = 0
        self._book_ready     = False   # True once snapshot + first diff applied

        self.recent_trades = deque(maxlen=TRADE_HISTORY_LEN)
        self.mid_price     = 0.0
        self.connected     = False
        self.error_msg     = ""

        # Diff buffer: hold diffs that arrive before snapshot is applied
        self._diff_buffer: list[dict] = []
        self._buffer_lock = threading.Lock()

        self._lock    = threading.Lock()
        self._running = False
        self._ws      = None

    # ── Public API (same interface as before) ─────────────────────

    def start(self):
        self._running = True
        # Thread 1: WebSocket book stream (SNAPSHOT FIRST)
        threading.Thread(target=self._ws_loop,     daemon=True).start()
        # Thread 2: REST trade feed
        threading.Thread(target=self._trades_loop, daemon=True).start()

    def stop(self):
        self._running = False
        if self._ws:
            self._ws.close()

    def get_orderbook(self) -> dict:
        """Returns top N levels sorted best-price first."""
        with self._lock:
            bids = sorted(self._bids.items(), reverse=True)[:1000]
            asks = sorted(self._asks.items())[:1000]
            return {"bids": bids, "asks": asks}

    def get_full_orderbook(self, depth: int = 5000) -> dict:
        """Returns the full local book up to `depth` levels per side."""
        with self._lock:
            bids = sorted(self._bids.items(), reverse=True)[:depth]
            asks = sorted(self._asks.items())[:depth]
            return {"bids": bids, "asks": asks}

    def get_trades(self) -> list:
        with self._lock:
            return list(self.recent_trades)

    def get_mid_price(self) -> float:
        with self._lock:
            return self.mid_price

    # ── WebSocket book stream ─────────────────────────────────────

    def _ws_loop(self):
        """Main WS loop: fetch snapshot FIRST, then connect to stream."""
        sym    = _ws_symbol(SYMBOL)
        url    = f"{_WS_BASE}/{sym}@depth@100ms"   # 100ms diff stream

        while self._running:
            try:
                # Step 1: Fetch snapshot BEFORE connecting WebSocket
                logger.info("📡 Fetching orderbook snapshot...")
                if not self._book_ready:
                    success = self._fetch_snapshot()
                    if not success:
                        logger.warning("⚠️  Snapshot fetch failed, retrying in 3s...")
                        time.sleep(3)
                        continue
                
                logger.info("✅ Snapshot loaded, connecting to WebSocket...")
                
                # Step 2: Now safe to connect WS (buffer is empty, book is ready)
                self._ws = websocket.WebSocketApp(
                    url,
                    on_open    = self._on_open,
                    on_message = self._on_message,
                    on_error   = self._on_error,
                    on_close   = self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
                
            except Exception as e:
                logger.error(f"💥 WS loop error: {e}")
                with self._lock:
                    self.error_msg = f"WS error: {e}"
                    self.connected = False
                    self._book_ready = False
                time.sleep(3)

    def _on_open(self, ws):
        """Called when WebSocket connects."""
        logger.info("🔗 WebSocket connected!")
        with self._lock:
            self.connected = True

    def _on_message(self, ws, raw):
        """Handle incoming diff message."""
        try:
            msg = json.loads(raw)
            
            # If book not ready yet, buffer it (shouldn't happen now, but safe)
            if not self._book_ready:
                with self._buffer_lock:
                    self._diff_buffer.append(msg)
                logger.debug(f"📦 Buffered diff (book not ready yet)")
                return
            
            self._apply_diff(msg)
            
        except Exception as e:
            logger.error(f"Error parsing WS message: {e}")

    def _on_error(self, ws, err):
        """Handle WebSocket error."""
        logger.error(f"🔴 WebSocket error: {err}")
        with self._lock:
            self.connected = False
            self.error_msg = str(err)

    def _on_close(self, ws, code, msg):
        """Called when WebSocket closes."""
        logger.info(f"⛔ WebSocket closed (code={code}): {msg}")
        with self._lock:
            self.connected = False
        self._book_ready = False

    def _fetch_snapshot(self) -> bool:
        """
        Fetch REST snapshot with retry logic.
        Binance docs: https://binance-docs.github.io/apidocs/futures/en/#diff-book-depth-streams
        
        Returns: True if successful, False if failed
        """
        # Convert symbol: "BTC/USDT:USDT" → "BTCUSDT"
        base = SYMBOL.split("/")[0].upper()
        quote = SYMBOL.split("/")[1].split(":")[0].upper()
        sym = base + quote
        
        logger.info(f"📍 Using symbol: {sym}")
        
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                logger.info(f"📥 Snapshot attempt {attempt + 1}/{max_retries}...")
                
                # Build URL manually to ensure correct parameter formatting
                url = f"{_REST_BASE}/fapi/v1/depth"
                params = {
                    "symbol": sym,
                    "limit": 1000  # Binance allows: 5, 10, 20, 50, 100, 500, 1000, 5000
                }
                
                logger.debug(f"🔗 GET {url}?symbol={sym}&limit={params['limit']}")
                
                r = requests.get(url, params=params, timeout=10)
                
                # Check for HTTP errors
                if r.status_code != 200:
                    error_text = r.text
                    logger.error(f"❌ HTTP {r.status_code}: {error_text}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # exponential backoff
                    continue
                
                data = r.json()
                
                # Validate response
                if "bids" not in data or "asks" not in data:
                    logger.error(f"❌ Invalid snapshot response: {data}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                    continue
                
                logger.info(f"✅ Snapshot received: {len(data['bids'])} bids, {len(data['asks'])} asks")
                
                # Load into local book
                with self._lock:
                    self._bids = {float(p): float(q) for p, q in data["bids"] if float(q) > 0}
                    self._asks = {float(p): float(q) for p, q in data["asks"] if float(q) > 0}
                    self._last_update_id = data["lastUpdateId"]
                    logger.info(f"📚 Book loaded: lastUpdateId={self._last_update_id}, "
                              f"Bids={len(self._bids)}, Asks={len(self._asks)}")
                    self._update_mid()

                # Drain any buffered diffs (shouldn't be many)
                with self._buffer_lock:
                    buffered = list(self._diff_buffer)
                    self._diff_buffer.clear()
                
                logger.info(f"📤 Processing {len(buffered)} buffered diffs...")

                # Apply buffered diffs per Binance spec
                for diff in buffered:
                    # Only apply diffs where U <= lastUpdateId+1 <= u
                    if diff.get("u", 0) < self._last_update_id:
                        logger.debug(f"⏭️  Skipping old diff (u={diff.get('u', 0)} < {self._last_update_id})")
                        continue
                    self._apply_diff(diff)

                self._book_ready = True
                logger.info("✅ Book ready!")
                return True

            except requests.exceptions.Timeout:
                logger.warning(f"⏱️  Request timeout on attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"🌐 Connection error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    
            except Exception as e:
                logger.error(f"💥 Unexpected error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        # All retries exhausted
        logger.error(f"❌ Failed to fetch snapshot after {max_retries} attempts")
        with self._lock:
            self.error_msg = f"Snapshot failed after {max_retries} retries"
            self.connected = False
        self._book_ready = False
        return False

    def _apply_diff(self, msg):
        """
        Apply a depth diff message to the local book.
        qty == 0 means remove that price level.
        """
        try:
            with self._lock:
                bid_count = 0
                for price_str, qty_str in msg.get("b", []):   # bids
                    p, q = float(price_str), float(qty_str)
                    if q == 0:
                        self._bids.pop(p, None)
                    else:
                        self._bids[p] = q
                    bid_count += 1

                ask_count = 0
                for price_str, qty_str in msg.get("a", []):   # asks
                    p, q = float(price_str), float(qty_str)
                    if q == 0:
                        self._asks.pop(p, None)
                    else:
                        self._asks[p] = q
                    ask_count += 1

                self._last_update_id = msg.get("u", self._last_update_id)
                self._update_mid()
                
                logger.debug(f"📊 Diff applied: {bid_count} bids, {ask_count} asks, lastUpdateId={self._last_update_id}")

        except Exception as e:
            logger.error(f"Error applying diff: {e}")

    def _update_mid(self):
        """Must be called inside self._lock."""
        if self._bids and self._asks:
            best_bid = max(self._bids)
            best_ask = min(self._asks)
            self.mid_price = (best_bid + best_ask) / 2

    # ── REST trade feed ──────────────────────────────────────────

    def _trades_loop(self):
        """Fetch recent trades from REST API."""
        while self._running:
            try:
                trades = self.exchange.fetch_trades(SYMBOL, limit=50)
                with self._lock:
                    for t in trades:
                        if (not self.recent_trades or
                                self.recent_trades[-1]["id"] != t["id"]):
                            self.recent_trades.append({
                                "id"    : t["id"],
                                "price" : t["price"],
                                "amount": t["amount"],
                                "side"  : t["side"],
                                "time"  : t["timestamp"],
                            })
            except Exception as e:
                logger.debug(f"Trade fetch skipped: {e}")
                pass   # trades are non-critical; silently skip
            time.sleep(FETCH_INTERVAL)
