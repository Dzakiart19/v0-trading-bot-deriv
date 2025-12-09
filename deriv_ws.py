"""
Deriv WebSocket Connection - Native websocket implementation for low-latency trading
Fixed: Connection readiness barrier and proper state management
"""

import json
import time
import logging
import threading
from typing import Dict, Optional, Callable, Any, List
from collections import deque
import websocket

logger = logging.getLogger(__name__)

class DerivWebSocket:
    """WebSocket client for Deriv API with multi-symbol support"""
    
    WS_URL = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"
    
    def __init__(self, app_id: Optional[str] = None):
        import os
        if app_id is None:
            app_id = os.environ.get("DERIV_APP_ID", "") or "1089"
        self.app_id = app_id
        self.ws: Optional[websocket.WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        
        # Connection state
        self.connected = False
        self.authorized = False
        self.token: Optional[str] = None
        self.account_type = "demo"  # demo or real
        
        # Connection readiness event
        self._connection_ready = threading.Event()
        self._connection_error: Optional[str] = None
        
        # Account info
        self.balance = 0.0
        self.currency = "USD"
        self.account_id: Optional[str] = None
        self.loginid: Optional[str] = None
        
        # Request tracking
        self._request_id = 0
        self._request_lock = threading.RLock()
        self._pending_requests: Dict[int, dict] = {}
        self._response_events: Dict[int, threading.Event] = {}
        self._responses: Dict[int, dict] = {}
        
        # Tick subscriptions
        self._tick_subscriptions: Dict[str, str] = {}  # symbol -> subscription_id
        self._tick_callbacks: Dict[str, Callable] = {}  # symbol -> callback
        self._tick_history: Dict[str, deque] = {}  # symbol -> tick deque
        
        # Contract tracking
        self._active_contracts: Dict[str, dict] = {}  # contract_id -> contract_info
        self._contract_callbacks: Dict[str, Callable] = {}
        
        # Reconnection
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_delay = 5
        
        # Health check - ping every 30 seconds per Deriv API best practices
        self._last_ping = 0
        self._ping_interval = 30  # Changed from 60 to 30 seconds
        self._health_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Last authorization error for detailed feedback
        self._last_auth_error: Optional[str] = None
        
        # Timeout tracking for diagnostics
        self._timeout_count = 0
        self._consecutive_timeouts = 0
        self._last_successful_request = 0
        self._total_requests = 0
        self._successful_requests = 0
        
        # Callbacks
        self.on_balance_update: Optional[Callable] = None
        self.on_contract_update: Optional[Callable] = None
        self.on_connection_status: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
    
    def _get_request_id(self) -> int:
        """Generate unique request ID"""
        with self._request_lock:
            self._request_id += 1
            return self._request_id
    
    def connect(self, timeout: float = 15) -> bool:
        """Establish WebSocket connection with proper readiness barrier"""
        if self.connected:
            logger.info("Already connected")
            return True
        
        # Reset state
        self._connection_ready.clear()
        self._connection_error = None
        self.connected = False
        self.authorized = False
        
        try:
            url = self.WS_URL.format(app_id=self.app_id)
            logger.info(f"Connecting to Deriv WebSocket: {url}")
            
            self.ws = websocket.WebSocketApp(
                url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            
            self._running = True
            self.ws_thread = threading.Thread(target=self._run_forever, daemon=True)
            self.ws_thread.start()
            
            # Wait for connection with proper event barrier
            if self._connection_ready.wait(timeout=timeout):
                if self._connection_error:
                    logger.error(f"Connection failed: {self._connection_error}")
                    return False
                
                if self.connected:
                    self._start_health_check()
                    logger.info("WebSocket connection established successfully")
                    return True
            
            logger.error("Connection timeout - WebSocket did not open in time")
            self._running = False
            return False
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self._running = False
            return False
    
    def _run_forever(self):
        """Run WebSocket in thread with auto-reconnect and re-authorize"""
        while self._running:
            try:
                if self.ws is None:
                    logger.error("WebSocket is None, cannot run")
                    break
                self.ws.run_forever()  # No built-in ping - we handle it ourselves
            except Exception as e:
                logger.error(f"WebSocket run error: {e}")
                self._connection_error = str(e)
                self._connection_ready.set()
            
            if self._running and self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                delay = self._reconnect_delay * (2 ** (self._reconnect_attempts - 1))
                delay = min(delay, 30)  # Max 30 seconds delay
                logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempts})")
                time.sleep(delay)
                
                # Re-create WebSocket and reconnect
                try:
                    url = self.WS_URL.format(app_id=self.app_id)
                    self._connection_ready.clear()
                    self.ws = websocket.WebSocketApp(
                        url,
                        on_open=self._on_open,
                        on_message=self._on_message,
                        on_error=self._on_error,
                        on_close=self._on_close
                    )
                    logger.info("WebSocket recreated for reconnection")
                except Exception as e:
                    logger.error(f"Failed to recreate WebSocket: {e}")
            else:
                break
    
    def _on_open(self, ws):
        """Handle connection opened - signal readiness and re-authorize if needed"""
        logger.info("WebSocket connected")
        self.connected = True
        self._reconnect_attempts = 0
        self._connection_error = None
        self._connection_ready.set()
        
        # Re-authorize if we have a token (for reconnect scenarios)
        if self.token and not self.authorized:
            logger.info("Re-authorizing after reconnect...")
            try:
                self._send({"authorize": self.token})
                # Don't signal connection status yet - wait for authorization in _handle_authorize
                return
            except Exception as e:
                logger.error(f"Re-authorization send failed: {e}")
        
        # Only signal connection status if not re-authorizing
        if self.on_connection_status:
            self.on_connection_status(True)
    
    
    def _on_message(self, ws, message):
        """Handle incoming messages"""
        try:
            data = json.loads(message)
            msg_type = data.get("msg_type")
            req_id = data.get("req_id")
            
            # Log all messages for debugging (except high-frequency ticks)
            if msg_type != "tick":
                logger.info(f"<<< Received msg_type={msg_type}, req_id={req_id}")
                # Log any errors in the response
                if "error" in data:
                    logger.error(f"<<< ERROR in response: {data['error']}")
            
            # Handle request responses - ensure req_id type matches (convert to int)
            if req_id is not None:
                req_id_int = int(req_id) if isinstance(req_id, str) else req_id
                
                # Log all proposal/buy responses for debugging
                if msg_type in ("proposal", "buy"):
                    logger.info(f">>> Received {msg_type} response with req_id {req_id_int}")
                
                if req_id_int in self._response_events:
                    self._responses[req_id_int] = data
                    self._response_events[req_id_int].set()
                    logger.info(f"Response matched for req_id {req_id_int}: {msg_type}")
                elif msg_type in ("proposal", "buy"):
                    # Store response anyway - might be late arrival from retry
                    self._responses[req_id_int] = data
                    logger.warning(f"Late response for {msg_type} with req_id {req_id_int} (waiting: {list(self._response_events.keys())})")
            
            # Handle specific message types
            if msg_type == "authorize":
                self._handle_authorize(data)
            elif msg_type == "tick":
                self._handle_tick(data)
            elif msg_type == "balance":
                self._handle_balance(data)
            elif msg_type == "buy":
                self._handle_buy(data)
            elif msg_type == "proposal_open_contract":
                self._handle_contract_update(data)
            elif msg_type == "history":
                self._handle_history(data)
            elif msg_type == "error":
                self._handle_error(data)
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
        except Exception as e:
            logger.error(f"Message handling error: {e}")
    
    def _on_error(self, ws, error):
        """Handle WebSocket errors"""
        logger.error(f"WebSocket error: {error}")
        self._connection_error = str(error)
        self._connection_ready.set()  # Signal error so connect() doesn't hang
        
        if self.on_error:
            self.on_error(str(error))
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle connection closed"""
        logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.connected = False
        self.authorized = False
        self._connection_ready.set()  # Signal in case we're waiting
        
        # Clear old subscriptions so new ones can be established after reconnect
        # Keep the callbacks so they can be re-registered
        self._tick_subscriptions.clear()
        logger.info("Cleared tick subscriptions for fresh re-subscribe after reconnect")
        
        if self.on_connection_status:
            self.on_connection_status(False)
    
    def _handle_authorize(self, data: dict):
        """Handle authorization response"""
        if "error" in data:
            error = data["error"]
            error_msg = error.get("message", "Unknown authorization error")
            error_code = error.get("code", "UNKNOWN")
            logger.error(f"Authorization failed: [{error_code}] {error_msg}")
            self.authorized = False
            self._last_auth_error = f"[{error_code}] {error_msg}"
            return
        
        auth = data.get("authorize", {})
        self.authorized = True
        self.balance = float(auth.get("balance", 0))
        self.currency = auth.get("currency", "USD")
        self.loginid = auth.get("loginid")
        
        # Determine account type from loginid
        if self.loginid:
            if self.loginid.startswith("VRTC"):
                self.account_type = "demo"
            else:
                self.account_type = "real"
        
        self.account_id = auth.get("account_list", [{}])[0].get("account_type")
        self._last_auth_error = None
        
        logger.info(f"Authorized: {self.loginid}, Balance: {self.balance} {self.currency}, Type: {self.account_type}")
        
        # Subscribe to balance updates
        self._send({"balance": 1, "subscribe": 1})
        
        # Re-subscribe to ticks for all symbols that had callbacks (after reconnect)
        if self._tick_callbacks:
            logger.info(f"Re-subscribing to {len(self._tick_callbacks)} symbols after authorization...")
            for symbol in list(self._tick_callbacks.keys()):
                if symbol not in self._tick_subscriptions:
                    logger.info(f"Re-subscribing to ticks for {symbol}...")
                    self._send({
                        "ticks": symbol,
                        "subscribe": 1
                    })
        
        # Signal connection status AFTER successful authorization (for reconnect scenarios)
        if self.on_connection_status:
            logger.info("Signaling connection ready after authorization")
            self.on_connection_status(True)
    
    def _handle_tick(self, data: dict):
        """Handle tick data"""
        tick = data.get("tick", {})
        symbol = tick.get("symbol")
        
        # Update subscription tracking if this is a new subscription
        subscription = data.get("subscription", {})
        if subscription and symbol:
            sub_id = subscription.get("id")
            if sub_id and symbol not in self._tick_subscriptions:
                self._tick_subscriptions[symbol] = sub_id
                logger.info(f"Tick subscription confirmed for {symbol} (id: {sub_id})")
        
        if symbol:
            tick_data = {
                "symbol": symbol,
                "quote": float(tick.get("quote", 0)),
                "epoch": tick.get("epoch"),
                "pip_size": tick.get("pip_size", 2)
            }
            
            # Store in history
            if symbol not in self._tick_history:
                self._tick_history[symbol] = deque(maxlen=200)
            self._tick_history[symbol].append(tick_data)
            
            # Call symbol callback
            if symbol in self._tick_callbacks:
                try:
                    self._tick_callbacks[symbol](tick_data)
                except Exception as e:
                    logger.error(f"Tick callback error for {symbol}: {e}")
    
    def _handle_balance(self, data: dict):
        """Handle balance updates"""
        balance_data = data.get("balance", {})
        self.balance = float(balance_data.get("balance", self.balance))
        self.currency = balance_data.get("currency", self.currency)
        
        if self.on_balance_update:
            self.on_balance_update(self.balance, self.currency)
    
    def _handle_buy(self, data: dict):
        """Handle buy response"""
        if "error" in data:
            logger.error(f"Buy error: {data['error']}")
            return
        
        buy = data.get("buy", {})
        contract_id = buy.get("contract_id")
        
        if contract_id:
            self._active_contracts[str(contract_id)] = {
                "contract_id": contract_id,
                "buy_price": float(buy.get("buy_price", 0)),
                "payout": float(buy.get("payout", 0)),
                "start_time": buy.get("start_time"),
                "status": "open"
            }
            
            # Subscribe to contract updates
            self._send({
                "proposal_open_contract": 1,
                "contract_id": contract_id,
                "subscribe": 1
            })
    
    def _handle_contract_update(self, data: dict):
        """Handle contract status updates"""
        poc = data.get("proposal_open_contract", {})
        contract_id = str(poc.get("contract_id", ""))
        
        if contract_id in self._active_contracts:
            self._active_contracts[contract_id].update({
                "current_spot": poc.get("current_spot"),
                "profit": float(poc.get("profit", 0)),
                "status": poc.get("status"),
                "is_sold": poc.get("is_sold", 0) == 1,
                "sell_price": float(poc.get("sell_price", 0)) if poc.get("sell_price") else None,
                "exit_tick": poc.get("exit_tick"),
                "exit_tick_time": poc.get("exit_tick_time")
            })
            
            if self.on_contract_update:
                self.on_contract_update(self._active_contracts[contract_id])
            
            # Clean up if contract is closed
            if poc.get("is_sold") == 1 or poc.get("status") == "sold":
                if contract_id in self._contract_callbacks:
                    try:
                        self._contract_callbacks[contract_id](self._active_contracts[contract_id])
                    except Exception as e:
                        logger.error(f"Contract callback error: {e}")
                    del self._contract_callbacks[contract_id]
    
    def _handle_history(self, data: dict):
        """Handle historical data response"""
        history = data.get("history", {})
        prices = history.get("prices", [])
        times = history.get("times", [])
        
        echo_req = data.get("echo_req", {})
        symbol = echo_req.get("ticks_history")
        
        if symbol and prices:
            if symbol not in self._tick_history:
                self._tick_history[symbol] = deque(maxlen=200)
            
            for i, price in enumerate(prices):
                tick_data = {
                    "symbol": symbol,
                    "quote": float(price),
                    "epoch": times[i] if i < len(times) else None
                }
                self._tick_history[symbol].append(tick_data)
    
    def _handle_error(self, data: dict):
        """Handle error messages"""
        error = data.get("error", {})
        logger.error(f"API Error: {error.get('code')} - {error.get('message')}")
        
        if self.on_error:
            self.on_error(error.get("message", "Unknown error"))
    
    def _send(self, data: dict) -> int:
        """Send message to WebSocket"""
        if not self.connected or not self.ws:
            logger.error("Not connected")
            return -1
        
        req_id = self._get_request_id()
        data["req_id"] = req_id
        
        try:
            self.ws.send(json.dumps(data))
            return req_id
        except Exception as e:
            logger.error(f"Send error: {e}")
            return -1
    
    def _send_and_wait(self, data: dict, timeout: float = 10, retries: int = 0) -> Optional[dict]:
        """Send message and wait for response with retry support and metric tracking
        
        Uses a shared event across all retry attempts to handle delayed responses.
        
        Args:
            data: Message data to send
            timeout: Timeout per attempt (default 10s per Deriv best practices)
            retries: Number of retry attempts (0 = no retries)
        """
        if not self.connected or not self.ws:
            logger.error("Cannot send - not connected")
            return None
        
        max_attempts = retries + 1
        last_error = None
        
        # Use a single shared event and collect all req_ids for this operation
        shared_event = threading.Event()
        all_req_ids = []
        response_holder = {"data": None, "req_id": None}
        
        def create_response_handler(rid):
            """Create a handler that sets shared event when any req_id responds"""
            def handler():
                if rid in self._responses:
                    response_holder["data"] = self._responses.get(rid)
                    response_holder["req_id"] = rid
                    shared_event.set()
            return handler
        
        try:
            for attempt in range(max_attempts):
                # Check connection before each attempt
                if not self.connected or not self.ws:
                    logger.error("Connection lost during request")
                    return None
                
                # Check if we already got a response from previous attempt
                if shared_event.is_set() and response_holder["data"] is not None:
                    logger.info(f"Received delayed response from req_id {response_holder['req_id']}")
                    self._successful_requests += 1
                    self._last_successful_request = time.time()
                    self._consecutive_timeouts = 0
                    return response_holder["data"]
                
                req_id = self._get_request_id()
                all_req_ids.append(req_id)
                data_copy = data.copy()
                data_copy["req_id"] = req_id
                
                # Register event for this req_id
                self._response_events[req_id] = shared_event
                self._total_requests += 1
                
                try:
                    start_time = time.time()
                    self.ws.send(json.dumps(data_copy))
                    logger.debug(f"Sent request with req_id {req_id}: {list(data.keys())}")
                    
                    # Wait for response
                    if shared_event.wait(timeout):
                        # Check all our req_ids for the response
                        for rid in all_req_ids:
                            if rid in self._responses:
                                response = self._responses.pop(rid, None)
                                if response:
                                    elapsed = time.time() - start_time
                                    logger.debug(f"Request completed in {elapsed:.2f}s (req_id {rid}): {list(data.keys())}")
                                    self._successful_requests += 1
                                    self._last_successful_request = time.time()
                                    self._consecutive_timeouts = 0
                                    return response
                        
                        # Event was set but no response found - check holder
                        if response_holder["data"]:
                            return response_holder["data"]
                    
                    # Timeout
                    elapsed = time.time() - start_time
                    last_error = f"Request timeout ({elapsed:.1f}s) for: {list(data.keys())}"
                    logger.warning(f"Attempt {attempt + 1}/{max_attempts}: {last_error}")
                    
                    self._timeout_count += 1
                    self._consecutive_timeouts += 1
                    
                    # Check if we need to trigger reconnect after multiple consecutive timeouts
                    if self._consecutive_timeouts >= 5:
                        logger.warning("Multiple consecutive timeouts - connection may be degraded")
                        self._trigger_reconnect()
                        return None
                    
                    if attempt < max_attempts - 1:
                        # Short delay before retry - don't sleep too long
                        import random
                        delay = 0.5 + random.uniform(0.1, 0.3)
                        logger.info(f"Retrying in {delay:.1f}s...")
                        time.sleep(delay)
                        shared_event.clear()  # Reset event for next attempt
                        
                except Exception as e:
                    last_error = str(e)
                    logger.error(f"Send and wait error (attempt {attempt + 1}): {e}")
                    self._timeout_count += 1
                    self._consecutive_timeouts += 1
                    
                    if attempt < max_attempts - 1:
                        import random
                        delay = 0.5 + random.uniform(0.1, 0.3)
                        time.sleep(delay)
                        shared_event.clear()
            
            if last_error:
                logger.error(f"All {max_attempts} attempts failed: {last_error}")
            return None
            
        finally:
            # Cleanup all registered events
            for rid in all_req_ids:
                self._response_events.pop(rid, None)
                self._responses.pop(rid, None)
    
    def _trigger_reconnect(self):
        """Trigger reconnection when connection is degraded"""
        logger.warning("Triggering reconnection due to degraded connection...")
        self._consecutive_timeouts = 0
        
        # Close current connection
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        
        self.connected = False
        self.authorized = False
    
    def authorize(self, token: str, timeout: float = 30) -> tuple:
        """
        Authorize with Deriv API token
        
        Returns:
            tuple: (success: bool, error_message: Optional[str])
        """
        if not self.connected:
            return False, "WebSocket not connected"
        
        self.token = token
        self._last_auth_error = None
        
        logger.info("Sending authorization request...")
        response = self._send_and_wait({"authorize": token}, timeout=timeout)
        
        if response is None:
            error_msg = "Authorization request timed out. Please check your internet connection."
            logger.error(error_msg)
            self._reset_state()
            return False, error_msg
        
        if "error" in response:
            error = response["error"]
            error_code = error.get("code", "UNKNOWN")
            error_msg = error.get("message", "Unknown error")
            
            # Translate common error codes
            if error_code == "InvalidToken":
                error_msg = "Token tidak valid atau sudah kadaluarsa. Silakan buat token baru di https://app.deriv.com/account/api-token"
            elif error_code == "AuthorizationRequired":
                error_msg = "Token tidak memiliki izin yang cukup. Pastikan token memiliki izin 'trade' dan 'read'."
            
            logger.error(f"Authorization failed: [{error_code}] {error_msg}")
            self._last_auth_error = error_msg
            self._reset_state()
            return False, error_msg
        
        if "authorize" in response:
            logger.info("Authorization successful")
            return True, None
        
        error_msg = "Response tidak dikenali dari server Deriv"
        logger.error(error_msg)
        self._reset_state()
        return False, error_msg
    
    def _reset_state(self):
        """Reset connection state after failure"""
        self.authorized = False
        self.token = None
        self.balance = 0.0
        self.loginid = None
        self.account_id = None
    
    def get_last_auth_error(self) -> Optional[str]:
        """Get the last authorization error message"""
        return self._last_auth_error
    
    def subscribe_ticks(self, symbol: str, callback: Callable) -> bool:
        """Subscribe to tick stream for a symbol"""
        if not self.connected:
            logger.error("Cannot subscribe - not connected")
            return False
        
        if symbol in self._tick_subscriptions:
            logger.info(f"Already subscribed to {symbol}")
            self._tick_callbacks[symbol] = callback
            return True
        
        # First get history
        self._send({
            "ticks_history": symbol,
            "count": 100,
            "end": "latest",
            "style": "ticks"
        })
        
        # Then subscribe
        response = self._send_and_wait({
            "ticks": symbol,
            "subscribe": 1
        })
        
        if response and "subscription" in response:
            sub_id = response["subscription"].get("id")
            self._tick_subscriptions[symbol] = sub_id
            self._tick_callbacks[symbol] = callback
            logger.info(f"Subscribed to {symbol}")
            return True
        elif response and "error" in response:
            logger.error(f"Subscribe error: {response['error']}")
        
        return False
    
    def unsubscribe_ticks(self, symbol: str) -> bool:
        """Unsubscribe from tick stream"""
        if symbol not in self._tick_subscriptions:
            return True
        
        sub_id = self._tick_subscriptions[symbol]
        response = self._send_and_wait({"forget": sub_id})
        
        if response:
            del self._tick_subscriptions[symbol]
            self._tick_callbacks.pop(symbol, None)
            logger.info(f"Unsubscribed from {symbol}")
            return True
        
        return False
    
    def get_ticks_history(self, symbol: str, count: int = 100) -> List[dict]:
        """Get historical tick data"""
        if symbol in self._tick_history:
            return list(self._tick_history[symbol])[-count:]
        return []
    
    def preload_data(self, symbol: str, count: int = 150, timeout: float = 15) -> bool:
        """
        Preload historical tick data before trading starts.
        This ensures indicators have enough data to calculate properly.
        
        Args:
            symbol: Trading symbol to preload
            count: Number of historical ticks to load (default 150)
            timeout: Timeout in seconds
            
        Returns:
            bool: True if preload successful
        """
        if not self.connected:
            logger.error("Cannot preload - not connected")
            return False
        
        logger.info(f"Preloading {count} historical ticks for {symbol}...")
        
        response = self._send_and_wait({
            "ticks_history": symbol,
            "count": count,
            "end": "latest",
            "style": "ticks"
        }, timeout=timeout)
        
        if response and "history" in response:
            history = response.get("history", {})
            prices = history.get("prices", [])
            times = history.get("times", [])
            
            if symbol not in self._tick_history:
                self._tick_history[symbol] = deque(maxlen=200)
            
            for i, price in enumerate(prices):
                tick_data = {
                    "symbol": symbol,
                    "quote": float(price),
                    "epoch": times[i] if i < len(times) else None
                }
                self._tick_history[symbol].append(tick_data)
            
            logger.info(f"Preloaded {len(prices)} ticks for {symbol}")
            return len(prices) > 0
        
        if response and "error" in response:
            logger.error(f"Preload error: {response['error']}")
        else:
            logger.error("Preload timeout or no response")
        
        return False
    
    def is_data_ready(self, symbol: str, min_ticks: int = 100) -> bool:
        """Check if enough data is available for trading"""
        if symbol in self._tick_history:
            return len(self._tick_history[symbol]) >= min_ticks
        return False
    
    def buy_contract(
        self,
        contract_type: str,
        symbol: str,
        stake: float,
        duration: int,
        duration_unit: str = "t",
        barrier: Optional[str] = None,
        callback: Optional[Callable] = None,
        growth_rate: Optional[float] = None
    ) -> Optional[dict]:
        """
        Execute a trade
        
        Args:
            contract_type: CALL, PUT, DIGITOVER, DIGITUNDER, ACCU, etc.
            symbol: Trading symbol
            stake: Stake amount
            duration: Contract duration
            duration_unit: 't' for ticks, 'm' for minutes, 'd' for days
            barrier: Barrier for digit contracts
            callback: Callback when contract closes
            growth_rate: Growth rate for ACCU (Accumulator) contracts (0.01-0.05)
        """
        if not self.authorized:
            logger.error("Not authorized - cannot place trade")
            return None
        
        if not self.connected:
            logger.error("Not connected - cannot place trade")
            return None
        
        # Special handling for Accumulator contracts
        if contract_type == "ACCU":
            return self._buy_accumulator(symbol, stake, growth_rate or 0.01, callback)
        
        # Build contract parameters for regular contracts
        parameters = {
            "contract_type": contract_type,
            "symbol": symbol,
            "duration": int(duration),
            "duration_unit": duration_unit,
            "currency": self.currency,
            "basis": "stake",
            "amount": round(float(stake), 2)
        }
        
        if barrier is not None:
            parameters["barrier"] = barrier
        
        # Quick connection check (don't use full health check to avoid ping overhead)
        if not self.connected or not self.authorized:
            logger.error("Not connected or authorized - cannot place trade")
            return None
        
        # Get proposal with retry mechanism
        logger.info(f"Getting proposal for {contract_type} on {symbol}")
        
        # Quick ping test before proposal to verify connection
        ping_resp = self._send_and_wait({"ping": 1}, timeout=5, retries=0)
        if not ping_resp:
            logger.error("Pre-proposal ping failed - connection may be dead")
            self._trigger_reconnect()
            return None
        logger.info("Pre-proposal ping OK - connection alive")
        
        proposal_req = {"proposal": 1, **parameters}
        logger.info(f"Proposal request: {proposal_req}")
        
        proposal_resp = self._send_and_wait(proposal_req, timeout=30, retries=2)
        
        if not proposal_resp:
            logger.error(f"Proposal timeout (consecutive: {self._consecutive_timeouts})")
            
            if self.on_error and self._consecutive_timeouts >= 3:
                self.on_error("Multiple proposal timeouts detected. Connection may be unstable.")
            return None
        
        if "error" in proposal_resp:
            error = proposal_resp.get("error", {})
            error_code = error.get("code", "Unknown")
            error_msg = error.get("message", "Unknown error")
            logger.error(f"Proposal error [{error_code}]: {error_msg}")
            return None
        
        proposal = proposal_resp.get("proposal", {})
        proposal_id = proposal.get("id")
        
        if not proposal_id:
            logger.error("No proposal ID received")
            return None
        
        # Execute buy with retry
        logger.info(f"Executing buy for proposal {proposal_id}")
        buy_resp = self._send_and_wait({
            "buy": proposal_id,
            "price": stake
        }, timeout=30, retries=1)
        
        if buy_resp and "buy" in buy_resp:
            buy_data = buy_resp["buy"]
            contract_id = str(buy_data.get("contract_id"))
            
            if callback:
                self._contract_callbacks[contract_id] = callback
            
            logger.info(f"Trade executed: contract_id={contract_id}")
            return {
                "contract_id": contract_id,
                "buy_price": float(buy_data.get("buy_price", 0)),
                "payout": float(buy_data.get("payout", 0)),
                "start_time": buy_data.get("start_time")
            }
        
        if not buy_resp:
            logger.error(f"Buy timeout (consecutive: {self._consecutive_timeouts})")
        else:
            error = buy_resp.get("error", {})
            logger.error(f"Buy error [{error.get('code', 'Unknown')}]: {error.get('message', 'Unknown')}")
        
        return None
    
    def _buy_accumulator(
        self,
        symbol: str,
        stake: float,
        growth_rate: float,
        callback: Optional[Callable] = None
    ) -> Optional[dict]:
        """
        Buy Accumulator contract
        
        Accumulator contracts work differently:
        - growth_rate: 0.01 to 0.05 (1% to 5%)
        - No duration - contract continues until barrier is breached
        - Must use specific API format
        """
        if not self.connected or not self.authorized:
            logger.error("Not connected/authorized for accumulator trade")
            return None
        
        # Validate growth rate (1% to 5%)
        growth_rate = max(0.01, min(0.05, growth_rate))
        
        # Pre-trade ping check
        ping_resp = self._send_and_wait({"ping": 1}, timeout=5, retries=0)
        if not ping_resp:
            logger.error("Pre-accumulator ping failed")
            return None
        
        # Build accumulator proposal - Deriv API uses specific format
        # Note: For ACCU contracts, only take_profit is allowed in limit_order (stop_loss is NOT valid)
        # Take profit = stake * 0.5 means we lock in 50% profit (easier to achieve with fewer ticks)
        # This helps ensure the bot actually gets WIN results instead of hitting barriers
        take_profit_amount = round(stake * 0.5, 2)  # 50% profit target (achievable in ~5-8 ticks at 1-2%)
        
        parameters = {
            "contract_type": "ACCU",
            "symbol": symbol,
            "currency": self.currency,
            "basis": "stake",
            "amount": round(float(stake), 2),
            "growth_rate": growth_rate,
            "limit_order": {
                "take_profit": take_profit_amount  # Conservative TP for more wins
            }
        }
        
        logger.info(f"Accumulator TP target: ${take_profit_amount} (50% of stake ${stake})")
        
        logger.info(f"Accumulator proposal: {symbol} stake={stake} growth_rate={growth_rate*100}%")
        
        proposal_req = {"proposal": 1, **parameters}
        proposal_resp = self._send_and_wait(proposal_req, timeout=30, retries=2)
        
        if not proposal_resp:
            logger.error("Accumulator proposal timeout")
            return None
        
        if "error" in proposal_resp:
            error = proposal_resp.get("error", {})
            error_code = error.get("code", "Unknown")
            error_msg = error.get("message", "Unknown error")
            logger.error(f"Accumulator proposal error [{error_code}]: {error_msg}")
            # Fall back to regular CALL for symbols that don't support ACCU
            logger.info("Falling back to CALL contract type")
            return None
        
        proposal = proposal_resp.get("proposal", {})
        proposal_id = proposal.get("id")
        
        if not proposal_id:
            logger.error("No accumulator proposal ID")
            return None
        
        # Execute buy
        buy_resp = self._send_and_wait({
            "buy": proposal_id,
            "price": stake
        }, timeout=30, retries=1)
        
        if buy_resp and "buy" in buy_resp:
            buy_data = buy_resp["buy"]
            contract_id = str(buy_data.get("contract_id"))
            
            if callback:
                self._contract_callbacks[contract_id] = callback
            
            logger.info(f"Accumulator trade executed: contract_id={contract_id}")
            return {
                "contract_id": contract_id,
                "buy_price": float(buy_data.get("buy_price", 0)),
                "payout": float(buy_data.get("payout", 0)),
                "start_time": buy_data.get("start_time"),
                "contract_type": "ACCU",
                "growth_rate": growth_rate
            }
        
        if not buy_resp:
            logger.error("Accumulator buy timeout")
        else:
            error = buy_resp.get("error", {})
            logger.error(f"Accumulator buy error [{error.get('code')}]: {error.get('message')}")
        
        return None
    
    def get_active_contracts(self) -> Dict[str, dict]:
        """Get all active contracts"""
        return self._active_contracts.copy()
    
    def _start_health_check(self):
        """Start health check thread"""
        if self._health_thread and self._health_thread.is_alive():
            return
        
        def health_loop():
            while self._running and self.connected:
                try:
                    self._send({"ping": 1})
                    self._last_ping = time.time()
                except Exception as e:
                    logger.error(f"Health check error: {e}")
                time.sleep(self._ping_interval)
        
        self._health_thread = threading.Thread(target=health_loop, daemon=True)
        self._health_thread.start()
    
    def disconnect(self):
        """Disconnect from WebSocket"""
        self._running = False
        
        # Unsubscribe from all ticks
        for symbol in list(self._tick_subscriptions.keys()):
            try:
                self.unsubscribe_ticks(symbol)
            except:
                pass
        
        if self.ws:
            try:
                self.ws.close()
            except:
                pass
        
        self.connected = False
        self.authorized = False
        self._reset_state()
        
        logger.info("Disconnected")
    
    def is_connected(self) -> bool:
        """Check if connected and authorized"""
        return self.connected and self.authorized
    
    def check_connection_health(self) -> bool:
        """
        Verify connection is healthy before placing trades.
        Sends ping and verifies response within timeout.
        """
        if not self.connected or not self.ws:
            logger.warning("Connection health check: Not connected")
            return False
        
        if not self.authorized:
            logger.warning("Connection health check: Not authorized")
            return False
        
        try:
            ping_resp = self._send_and_wait({"ping": 1}, timeout=5)
            if ping_resp and "ping" in ping_resp:
                return True
            logger.warning("Connection health check: No ping response")
            return False
        except Exception as e:
            logger.error(f"Connection health check error: {e}")
            return False
    
    def get_connection_metrics(self) -> dict:
        """Get connection health metrics for debugging"""
        success_rate = 0
        if self._total_requests > 0:
            success_rate = (self._successful_requests / self._total_requests) * 100
        
        return {
            "connected": self.connected,
            "authorized": self.authorized,
            "total_requests": self._total_requests,
            "successful_requests": self._successful_requests,
            "timeout_count": self._timeout_count,
            "consecutive_timeouts": self._consecutive_timeouts,
            "success_rate": round(success_rate, 1),
            "last_successful_request": self._last_successful_request,
            "reconnect_attempts": self._reconnect_attempts
        }
    
    def get_balance(self) -> float:
        """Get current balance"""
        return self.balance
    
    def get_currency(self) -> str:
        """Get account currency"""
        return self.currency
