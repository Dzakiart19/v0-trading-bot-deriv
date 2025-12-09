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
    
    def __init__(self, app_id: str = None):
        import os
        if app_id is None:
            app_id = os.environ.get("DERIV_APP_ID", "1089")
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
        
        # Health check
        self._last_ping = 0
        self._ping_interval = 60
        self._health_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Last authorization error for detailed feedback
        self._last_auth_error: Optional[str] = None
        
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
        """Run WebSocket in thread"""
        while self._running:
            try:
                self.ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.error(f"WebSocket run error: {e}")
                self._connection_error = str(e)
                self._connection_ready.set()
            
            if self._running and self._reconnect_attempts < self._max_reconnect_attempts:
                self._reconnect_attempts += 1
                delay = self._reconnect_delay * (2 ** (self._reconnect_attempts - 1))
                delay = min(delay, 60)
                logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempts})")
                time.sleep(delay)
            else:
                break
    
    def _on_open(self, ws):
        """Handle connection opened - signal readiness"""
        logger.info("WebSocket connected")
        self.connected = True
        self._reconnect_attempts = 0
        self._connection_error = None
        self._connection_ready.set()  # Signal that connection is ready
        
        if self.on_connection_status:
            self.on_connection_status(True)
    
    def _on_message(self, ws, message):
        """Handle incoming messages"""
        try:
            data = json.loads(message)
            msg_type = data.get("msg_type")
            req_id = data.get("req_id")
            
            # Handle request responses
            if req_id and req_id in self._response_events:
                self._responses[req_id] = data
                self._response_events[req_id].set()
            
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
    
    def _handle_tick(self, data: dict):
        """Handle tick data"""
        tick = data.get("tick", {})
        symbol = tick.get("symbol")
        
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
    
    def _send_and_wait(self, data: dict, timeout: float = 30) -> Optional[dict]:
        """Send message and wait for response"""
        if not self.connected or not self.ws:
            logger.error("Cannot send - not connected")
            return None
        
        req_id = self._get_request_id()
        data["req_id"] = req_id
        
        event = threading.Event()
        self._response_events[req_id] = event
        
        try:
            self.ws.send(json.dumps(data))
            
            if event.wait(timeout):
                response = self._responses.pop(req_id, None)
                return response
            else:
                logger.error(f"Request timeout for: {list(data.keys())}")
                return None
        except Exception as e:
            logger.error(f"Send and wait error: {e}")
            return None
        finally:
            self._response_events.pop(req_id, None)
    
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
    
    def buy_contract(
        self,
        contract_type: str,
        symbol: str,
        stake: float,
        duration: int,
        duration_unit: str = "t",
        barrier: Optional[str] = None,
        callback: Optional[Callable] = None
    ) -> Optional[dict]:
        """
        Execute a trade
        
        Args:
            contract_type: CALL, PUT, DIGITOVER, DIGITUNDER, etc.
            symbol: Trading symbol
            stake: Stake amount
            duration: Contract duration
            duration_unit: 't' for ticks, 'm' for minutes, 'd' for days
            barrier: Barrier for digit contracts
            callback: Callback when contract closes
        """
        if not self.authorized:
            logger.error("Not authorized - cannot place trade")
            return None
        
        if not self.connected:
            logger.error("Not connected - cannot place trade")
            return None
        
        # Build contract parameters
        parameters = {
            "contract_type": contract_type,
            "symbol": symbol,
            "duration": duration,
            "duration_unit": duration_unit,
            "currency": self.currency,
            "basis": "stake",
            "amount": stake
        }
        
        if barrier is not None:
            parameters["barrier"] = barrier
        
        # Get proposal first
        logger.info(f"Getting proposal for {contract_type} on {symbol}")
        proposal_req = {"proposal": 1, **parameters}
        proposal_resp = self._send_and_wait(proposal_req, timeout=15)
        
        if not proposal_resp or "error" in proposal_resp:
            error = proposal_resp.get("error", {}) if proposal_resp else {}
            logger.error(f"Proposal error: {error.get('message', 'Unknown')}")
            return None
        
        proposal = proposal_resp.get("proposal", {})
        proposal_id = proposal.get("id")
        
        if not proposal_id:
            logger.error("No proposal ID received")
            return None
        
        # Execute buy
        logger.info(f"Executing buy for proposal {proposal_id}")
        buy_resp = self._send_and_wait({
            "buy": proposal_id,
            "price": stake
        }, timeout=15)
        
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
        
        error = buy_resp.get("error", {}) if buy_resp else {}
        logger.error(f"Buy error: {error.get('message', 'Unknown')}")
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
    
    def get_balance(self) -> float:
        """Get current balance"""
        return self.balance
    
    def get_currency(self) -> str:
        """Get account currency"""
        return self.currency
