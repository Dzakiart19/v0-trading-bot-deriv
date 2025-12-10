"""
Web Server - FastAPI with WebSocket and multi-strategy WebApps
Serves HTML files from webapps/ folder and provides API for Deriv trading
"""

import os
import json
import hmac
import hashlib
import logging
import asyncio
import secrets
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import threading

from trading import TradingManager, TradingConfig, TradingState, StrategyType
from performance_monitor import performance_monitor
from user_preferences import user_preferences

logger = logging.getLogger(__name__)

# ==================== Models ====================

class TelegramAuthData(BaseModel):
    init_data: str
    
class TradeRequest(BaseModel):
    symbol: str
    direction: str
    stake: float
    duration: int = 5
    duration_unit: str = "t"
    contract_type: Optional[str] = None
    barrier: Optional[str] = None
    
class AutoTradeConfig(BaseModel):
    symbol: str
    strategy: str
    base_stake: float = 1.0
    target_trades: int = 10
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None

class DerivTokenSync(BaseModel):
    telegram_id: int
    token: str

class TradingStartRequest(BaseModel):
    telegram_id: int
    symbol: str
    strategy: str
    stake: float
    target_trades: Optional[int] = 10

class TradingStopRequest(BaseModel):
    telegram_id: int


# ==================== WebSocket Manager ====================

class ConnectionManager:
    """Manage WebSocket connections with heartbeat and session validation"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_strategies: Dict[str, str] = {}
        self.connection_info: Dict[str, Dict] = {}  # user_id -> {telegram_id, connected_at, last_ping}
        self.telegram_to_user: Dict[int, str] = {}  # telegram_id -> user_id mapping
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_interval = 30  # Send ping every 30 seconds
        self._connection_timeout = 90  # Disconnect if no pong for 90 seconds
    
    async def connect(self, websocket: WebSocket, user_id: str, telegram_id: Optional[int] = None):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        self.connection_info[user_id] = {
            "telegram_id": telegram_id,
            "connected_at": datetime.now().isoformat(),
            "last_ping": datetime.now().timestamp(),
            "last_pong": datetime.now().timestamp()
        }
        if telegram_id:
            self.telegram_to_user[telegram_id] = user_id
        logger.info(f"WebSocket connected: user_id={user_id}, telegram_id={telegram_id}")
    
    def disconnect(self, user_id: str):
        """Remove connection from tracking (sync version for compatibility)"""
        ws = self.active_connections.pop(user_id, None)
        info = self.connection_info.pop(user_id, None)
        if info and info.get("telegram_id"):
            self.telegram_to_user.pop(info["telegram_id"], None)
        logger.info(f"WebSocket disconnected: {user_id}")
        return ws
    
    async def disconnect_and_close(self, user_id: str):
        """Remove connection and close WebSocket properly"""
        ws = self.disconnect(user_id)
        if ws:
            try:
                await ws.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket for {user_id}: {e}")
    
    def update_pong(self, user_id: str):
        """Update last pong timestamp when client responds to ping"""
        if user_id in self.connection_info:
            self.connection_info[user_id]["last_pong"] = datetime.now().timestamp()
    
    def get_user_by_telegram(self, telegram_id: int) -> Optional[str]:
        """Get user_id from telegram_id"""
        return self.telegram_to_user.get(telegram_id)
    
    def is_connected(self, user_id: str) -> bool:
        """Check if user is connected"""
        return user_id in self.active_connections
    
    async def send_personal(self, user_id: str, data: dict):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(data)
            except Exception as e:
                logger.error(f"Error sending to {user_id}: {e}")
                self.disconnect(user_id)
    
    async def send_to_telegram_user(self, telegram_id: int, data: dict):
        """Send message to user by telegram_id"""
        user_id = self.telegram_to_user.get(telegram_id)
        if user_id:
            await self.send_personal(user_id, data)
        else:
            # Fallback: try using telegram_id as user_id (old behavior)
            await self.send_personal(str(telegram_id), data)
    
    async def broadcast(self, data: dict):
        for user_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(data)
            except Exception as e:
                logger.error(f"Error broadcasting to {user_id}: {e}")
                self.disconnect(user_id)
    
    def set_strategy(self, user_id: str, strategy: str):
        self.user_strategies[user_id] = strategy
    
    def get_strategy(self, user_id: str) -> Optional[str]:
        return self.user_strategies.get(user_id)
    
    def get_connection_count(self) -> int:
        """Get number of active connections"""
        return len(self.active_connections)
    
    def get_all_connections(self) -> List[Dict]:
        """Get info about all active connections"""
        return [
            {"user_id": uid, **info}
            for uid, info in self.connection_info.items()
        ]
    
    async def start_heartbeat(self):
        """Start server-side heartbeat background task"""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("Started WebSocket heartbeat task")
    
    async def stop_heartbeat(self):
        """Stop server-side heartbeat background task"""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped WebSocket heartbeat task")
    
    async def _heartbeat_loop(self):
        """Background loop to ping clients and remove stale connections"""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                current_time = datetime.now().timestamp()
                
                users_to_disconnect = []
                
                for user_id in list(self.active_connections.keys()):
                    info = self.connection_info.get(user_id)
                    if not info:
                        continue
                    
                    last_pong = info.get("last_pong", current_time)
                    time_since_pong = current_time - last_pong
                    
                    if time_since_pong > self._connection_timeout:
                        logger.warning(f"Connection timeout for {user_id} (no pong for {time_since_pong:.1f}s)")
                        users_to_disconnect.append(user_id)
                    else:
                        ws = self.active_connections.get(user_id)
                        if ws:
                            try:
                                await ws.send_json({
                                    "type": "ping",
                                    "timestamp": current_time
                                })
                                self.connection_info[user_id]["last_ping"] = current_time
                            except Exception as e:
                                logger.error(f"Error sending ping to {user_id}: {e}")
                                users_to_disconnect.append(user_id)
                
                for user_id in users_to_disconnect:
                    await self.disconnect_and_close(user_id)
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat loop error: {e}")
                await asyncio.sleep(5)


# ==================== Session Manager ====================

class WebSessionManager:
    """Manage web sessions linked to Telegram"""
    
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.telegram_to_session: Dict[int, str] = {}
        self.user_strategy: Dict[int, str] = {}
        self.deriv_tokens: Dict[int, str] = {}
        self.deriv_accounts: Dict[int, Dict] = {}
    
    def create_session(self, telegram_user_id: int, user_data: dict) -> str:
        """Create session from Telegram auth"""
        if telegram_user_id in self.telegram_to_session:
            return self.telegram_to_session[telegram_user_id]
        
        token = secrets.token_urlsafe(32)
        self.sessions[token] = {
            "user_id": str(telegram_user_id),
            "telegram_id": telegram_user_id,
            "username": user_data.get("username", ""),
            "first_name": user_data.get("first_name", ""),
            "created_at": datetime.now().isoformat()
        }
        self.telegram_to_session[telegram_user_id] = token
        return token
    
    def get_session(self, token: str) -> Optional[Dict]:
        return self.sessions.get(token)
    
    def get_session_by_telegram(self, telegram_id: int) -> Optional[Dict]:
        token = self.telegram_to_session.get(telegram_id)
        if token:
            return self.sessions.get(token)
        return None
    
    def set_strategy(self, telegram_id: int, strategy: str):
        self.user_strategy[telegram_id] = strategy
    
    def get_strategy(self, telegram_id: int) -> Optional[str]:
        return self.user_strategy.get(telegram_id)
    
    def set_deriv_token(self, telegram_id: int, token: str):
        self.deriv_tokens[telegram_id] = token
    
    def get_deriv_token(self, telegram_id: int) -> Optional[str]:
        return self.deriv_tokens.get(telegram_id)
    
    def set_deriv_account(self, telegram_id: int, account_data: dict):
        self.deriv_accounts[telegram_id] = account_data
    
    def get_deriv_account(self, telegram_id: int) -> Optional[dict]:
        return self.deriv_accounts.get(telegram_id)
    
    def invalidate(self, token: str):
        session = self.sessions.pop(token, None)
        if session:
            self.telegram_to_session.pop(session.get("telegram_id"), None)
    
    def clear_user_data(self, telegram_id: int):
        """Clear all user data from session manager - used on logout"""
        self.deriv_tokens.pop(telegram_id, None)
        self.deriv_accounts.pop(telegram_id, None)
        self.user_strategy.pop(telegram_id, None)
        # Also clear session if exists
        token = self.telegram_to_session.pop(telegram_id, None)
        if token:
            self.sessions.pop(token, None)


# ==================== Global State ====================

manager = ConnectionManager()
session_manager = WebSessionManager()
_main_event_loop: Optional[asyncio.AbstractEventLoop] = None


# ==================== Trade Event Broadcasting ====================

async def broadcast_trade_event(event_type: str, data: dict, user_id: str = None):
    """
    Broadcast trade event to connected websockets with standardized format
    
    Event types and expected data format:
    - trade_opened: {contract_id, stake, contract_type, symbol}
    - trade_closed: {profit, balance, trades, win_rate, contract_id}
    - status_update: {is_running, trades, profit, win_rate, balance}
    """
    payload = {"type": event_type, "data": data}
    if user_id:
        await manager.send_personal(user_id, payload)
    else:
        await manager.broadcast(payload)


async def broadcast_trade_opened(contract_id: str, stake: float, contract_type: str, 
                                  symbol: str = "", user_id: str = None, telegram_id: int = None):
    """
    Broadcast trade opened event
    
    Args:
        contract_id: The Deriv contract ID
        stake: The stake amount
        contract_type: Type of contract (CALL, PUT, DIGITOVER, etc.)
        symbol: Trading symbol (e.g., R_100)
        user_id: WebSocket user_id (optional)
        telegram_id: Telegram user ID to find WebSocket connection (optional)
    """
    data = {
        "contract_id": contract_id,
        "stake": stake,
        "contract_type": contract_type,
        "symbol": symbol
    }
    
    # Resolve user_id from telegram_id if needed
    target_user_id = user_id
    if not target_user_id and telegram_id:
        target_user_id = str(telegram_id)
    
    await broadcast_trade_event("trade_opened", data, target_user_id)
    logger.info(f"Broadcasted trade_opened: {contract_type} on {symbol}, stake={stake}")


async def broadcast_trade_closed(profit: float, balance: float, trades: int, win_rate: float,
                                  contract_id: str = "", user_id: str = None, telegram_id: int = None):
    """
    Broadcast trade closed event
    
    Args:
        profit: Profit/loss from the trade
        balance: Current balance after trade
        trades: Total number of trades
        win_rate: Current win rate percentage
        contract_id: The Deriv contract ID (optional)
        user_id: WebSocket user_id (optional)
        telegram_id: Telegram user ID to find WebSocket connection (optional)
    """
    data = {
        "profit": profit,
        "balance": balance,
        "trades": trades,
        "win_rate": win_rate,
        "contract_id": contract_id
    }
    
    # Resolve user_id from telegram_id if needed
    target_user_id = user_id
    if not target_user_id and telegram_id:
        target_user_id = str(telegram_id)
    
    await broadcast_trade_event("trade_closed", data, target_user_id)
    logger.info(f"Broadcasted trade_closed: profit={profit}, balance={balance}, win_rate={win_rate}%")


async def broadcast_status_update(is_running: bool, trades: int, profit: float, win_rate: float,
                                   balance: float = 0.0, symbol: str = "", strategy: str = "",
                                   user_id: str = None, telegram_id: int = None):
    """
    Broadcast trading status update
    
    Args:
        is_running: Whether trading is currently active
        trades: Total number of trades
        profit: Total profit/loss
        win_rate: Current win rate percentage
        balance: Current account balance (optional)
        symbol: Current trading symbol (optional)
        strategy: Current strategy name (optional)
        user_id: WebSocket user_id (optional)
        telegram_id: Telegram user ID to find WebSocket connection (optional)
    """
    data = {
        "is_running": is_running,
        "trades": trades,
        "profit": profit,
        "win_rate": win_rate,
        "balance": balance,
        "symbol": symbol,
        "strategy": strategy
    }
    
    # Resolve user_id from telegram_id if needed
    target_user_id = user_id
    if not target_user_id and telegram_id:
        target_user_id = str(telegram_id)
    
    await broadcast_trade_event("status_update", data, target_user_id)
    logger.info(f"Broadcasted status_update: running={is_running}, trades={trades}, profit={profit}")


async def broadcast_to_telegram_user(telegram_id: int, event_type: str, data: dict):
    """
    Broadcast event to a specific user based on their Telegram ID
    
    This function finds the WebSocket connection associated with the telegram_id
    and sends the event to that specific user.
    
    Args:
        telegram_id: The Telegram user ID
        event_type: Type of event (trade_opened, trade_closed, status_update, etc.)
        data: Event data dictionary
    """
    user_id = str(telegram_id)
    payload = {"type": event_type, "data": data}
    
    if user_id in manager.active_connections:
        await manager.send_personal(user_id, payload)
        logger.debug(f"Sent {event_type} to telegram_id: {telegram_id}")
    else:
        logger.debug(f"No active WebSocket for telegram_id: {telegram_id}")


def clear_all_trading_state():
    """
    Clear all trading state from memory - called on startup/shutdown
    Clears trading_managers, deriv_connections, and session data
    """
    global trading_managers, deriv_connections
    
    # Stop all active trading managers
    for telegram_id, tm in list(trading_managers.items()):
        try:
            if hasattr(tm, 'stop'):
                tm.stop()
        except Exception as e:
            logger.error(f"Error stopping trading manager for {telegram_id}: {e}")
    
    # Clear all dictionaries
    trading_managers.clear()
    deriv_connections.clear()
    strategy_instances.clear()
    
    # Clear session manager data
    session_manager.sessions.clear()
    session_manager.telegram_to_session.clear()
    session_manager.user_strategy.clear()
    session_manager.deriv_tokens.clear()
    session_manager.deriv_accounts.clear()
    
    logger.info("Cleared all trading state from web_server memory")


strategy_instances: Dict[str, Any] = {}
deriv_connections: Dict[int, Any] = {}
trading_managers: Dict[int, Any] = {}

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DERIV_APP_ID = os.environ.get("DERIV_APP_ID", "") or "1089"


# ==================== Trading Manager Registration ====================

def register_trading_manager(telegram_id: int, trading_manager: TradingManager):
    """
    Register a TradingManager and set up WebSocket broadcasting callbacks.
    
    This function connects the TradingManager's trade events to the WebSocket
    broadcasting system so clients receive real-time updates.
    
    Uses asyncio.run_coroutine_threadsafe() to safely schedule coroutines
    from worker threads back to the main event loop.
    
    Args:
        telegram_id: The Telegram user ID
        trading_manager: The TradingManager instance to register
    """
    
    def on_trade_opened(trade_data: dict):
        """Callback when trade is opened - broadcast to WebSocket (thread-safe)"""
        if _main_event_loop is None:
            logger.warning("Main event loop not available for trade_opened broadcast")
            return
        try:
            coro = broadcast_trade_opened(
                contract_id=str(trade_data.get("contract_id", "")),
                stake=trade_data.get("stake", 0),
                contract_type=trade_data.get("contract_type", ""),
                symbol=trade_data.get("symbol", ""),
                telegram_id=telegram_id
            )
            asyncio.run_coroutine_threadsafe(coro, _main_event_loop)
        except Exception as e:
            logger.error(f"Error scheduling trade_opened broadcast: {e}")
    
    def on_trade_closed(trade_data: dict):
        """Callback when trade is closed - broadcast to WebSocket (thread-safe)"""
        if _main_event_loop is None:
            logger.warning("Main event loop not available for trade_closed broadcast")
            return
        try:
            coro = broadcast_trade_closed(
                profit=trade_data.get("profit", 0),
                balance=trade_data.get("balance", 0),
                trades=trade_data.get("trades", 0),
                win_rate=trade_data.get("win_rate", 0),
                contract_id=str(trade_data.get("contract_id", "")),
                telegram_id=telegram_id
            )
            asyncio.run_coroutine_threadsafe(coro, _main_event_loop)
        except Exception as e:
            logger.error(f"Error scheduling trade_closed broadcast: {e}")
    
    def on_session_complete(session_data: dict):
        """Callback when session ends - broadcast final status (thread-safe)"""
        if _main_event_loop is None:
            logger.warning("Main event loop not available for session_complete broadcast")
            return
        try:
            coro = broadcast_status_update(
                is_running=False,
                trades=session_data.get("trades", 0),
                profit=session_data.get("profit", 0),
                win_rate=session_data.get("win_rate", 0),
                balance=session_data.get("final_balance", 0),
                telegram_id=telegram_id
            )
            asyncio.run_coroutine_threadsafe(coro, _main_event_loop)
        except Exception as e:
            logger.error(f"Error scheduling session_complete broadcast: {e}")
    
    trading_manager.on_trade_opened = on_trade_opened
    trading_manager.on_trade_closed = on_trade_closed
    trading_manager.on_session_complete = on_session_complete
    
    trading_managers[telegram_id] = trading_manager
    logger.info(f"Registered TradingManager for telegram_id: {telegram_id}")


def unregister_trading_manager(telegram_id: int):
    """
    Unregister a TradingManager and clean up callbacks.
    
    Args:
        telegram_id: The Telegram user ID
    """
    if telegram_id in trading_managers:
        tm = trading_managers.pop(telegram_id)
        tm.on_trade_opened = None
        tm.on_trade_closed = None
        tm.on_session_complete = None
        logger.info(f"Unregistered TradingManager for telegram_id: {telegram_id}")


# ==================== FastAPI App ====================

app = FastAPI(title="Deriv Trading Bot API", version="2.0")


@app.on_event("startup")
async def startup_event():
    """Start heartbeat and initialize state on server startup"""
    global _main_event_loop
    logger.info("Starting web server...")
    _main_event_loop = asyncio.get_running_loop()
    await manager.start_heartbeat()
    performance_monitor.start()
    logger.info("Web server started successfully")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up on server shutdown"""
    logger.info("Shutting down web server...")
    await manager.stop_heartbeat()
    performance_monitor.stop()
    clear_all_trading_state()
    logger.info("Web server shutdown complete")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for webapps assets
if os.path.exists("webapps"):
    app.mount("/static", StaticFiles(directory="webapps"), name="static")


# ==================== Static WebApp Routes ====================

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve main index page from webapps folder"""
    try:
        with open("webapps/index.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Index not found</h1>", status_code=404)

@app.get("/index.html", response_class=HTMLResponse)
async def serve_index_html():
    """Serve index.html - alias for / route"""
    try:
        with open("webapps/index.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Index not found</h1>", status_code=404)

@app.get("/terminal", response_class=HTMLResponse)
async def serve_terminal():
    """Serve Terminal strategy page"""
    try:
        with open("webapps/terminal.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Terminal not found</h1>", status_code=404)

@app.get("/tick-picker", response_class=HTMLResponse)
async def serve_tick_picker():
    """Serve Tick Picker strategy page"""
    try:
        with open("webapps/tick-picker.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Tick Picker not found</h1>", status_code=404)

@app.get("/digitpad", response_class=HTMLResponse)
async def serve_digitpad():
    """Serve DigitPad strategy page"""
    try:
        with open("webapps/digitpad.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>DigitPad not found</h1>", status_code=404)

@app.get("/amt", response_class=HTMLResponse)
async def serve_amt():
    """Serve AMT Accumulator strategy page"""
    try:
        with open("webapps/amt.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>AMT not found</h1>", status_code=404)

@app.get("/sniper", response_class=HTMLResponse)
async def serve_sniper():
    """Serve Sniper strategy page"""
    try:
        with open("webapps/sniper.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Sniper not found</h1>", status_code=404)

@app.get("/multi-indicator", response_class=HTMLResponse)
async def serve_multi_indicator():
    """Serve Multi-Indicator strategy page"""
    try:
        with open("webapps/multi-indicator.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Multi-Indicator not found</h1>", status_code=404)

@app.get("/ldp", response_class=HTMLResponse)
async def serve_ldp():
    """Serve LDP Analyzer strategy page"""
    try:
        with open("webapps/ldp.html", "r") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>LDP Analyzer not found</h1>", status_code=404)


@app.get("/api/metrics")
async def get_metrics():
    """
    Get performance metrics for monitoring
    
    Returns:
        JSON with current performance metrics including:
        - Tick processing time
        - WebSocket latency
        - Trade execution time
        - Memory usage
        - Error rate
        - Health status
    """
    return JSONResponse(content=performance_monitor.get_metrics_json())


@app.get("/api/metrics/summary")
async def get_metrics_summary():
    """Get simplified performance metrics summary"""
    return JSONResponse(content=performance_monitor.get_summary())


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    metrics = performance_monitor.get_metrics()
    return JSONResponse(content={
        "status": "healthy" if metrics.is_healthy else "degraded",
        "uptime_seconds": performance_monitor.get_summary().get("uptime_minutes", 0) * 60,
        "active_connections": len(manager.active_connections),
        "active_traders": len(trading_managers)
    })


@app.get("/api/user/{telegram_id}/preferences")
async def get_user_preferences(telegram_id: int):
    """Get user preferences"""
    prefs = user_preferences.get(telegram_id)
    return JSONResponse(content=prefs.to_dict())


@app.post("/api/user/{telegram_id}/preferences")
async def update_user_preferences(telegram_id: int, request: Request):
    """Update user preferences"""
    try:
        data = await request.json()
        prefs = user_preferences.update(telegram_id, **data)
        return JSONResponse(content={"success": True, "preferences": prefs.to_dict()})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=400)


@app.get("/api/user/{telegram_id}/last-session")
async def get_last_session_config(telegram_id: int):
    """Get last session configuration for restore"""
    config = user_preferences.get_last_session_config(telegram_id)
    return JSONResponse(content=config)




# ==================== Telegram WebApp Auth ====================

TELEGRAM_AUTH_MAX_AGE = 600  # 10 minutes max age for initData

def verify_telegram_webapp(init_data: str) -> Optional[Dict]:
    """Verify Telegram WebApp init data with auth_date freshness check"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return None
    
    try:
        import urllib.parse
        import time
        
        # Parse using parse_qsl to properly handle plus signs as spaces (application/x-www-form-urlencoded)
        parsed_pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        params = dict(parsed_pairs)
        
        received_hash = params.pop("hash", "")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Use timing-safe comparison to prevent timing attacks
        if not hmac.compare_digest(calculated_hash, received_hash):
            logger.error("Invalid Telegram WebApp hash")
            return None
        
        # Check auth_date freshness to prevent replay attacks
        auth_date_str = params.get("auth_date")
        if not auth_date_str:
            logger.error("Missing auth_date in initData")
            return None
        
        try:
            auth_date = int(auth_date_str)
            current_time = int(time.time())
            if current_time - auth_date > TELEGRAM_AUTH_MAX_AGE:
                logger.error(f"Telegram initData expired: auth_date={auth_date}, current={current_time}")
                return None
        except (ValueError, TypeError):
            logger.error("Invalid auth_date format")
            return None
        
        # User is already decoded by parse_qsl
        user_str = params.get("user", "{}")
        user_data = json.loads(user_str)
        
        return {
            "user": user_data,
            "auth_date": auth_date_str,
            "query_id": params.get("query_id")
        }
    except Exception as e:
        logger.error(f"Telegram auth error: {e}")
        return None


# ==================== API Routes ====================

@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.get("/api/deriv/app-id")
async def get_deriv_app_id():
    """Get Deriv App ID for OAuth"""
    return {"app_id": DERIV_APP_ID}

@app.get("/api/strategy/configs")
async def get_strategy_configs():
    """Get all strategy configurations with stake options and trade count options"""
    from strategy_config import get_all_strategy_configs
    return get_all_strategy_configs()

@app.get("/api/strategy/{strategy_name}/config")
async def get_single_strategy_config(strategy_name: str):
    """Get configuration for a specific strategy"""
    from strategy_config import get_strategy_config
    config = get_strategy_config(strategy_name)
    if not config:
        raise HTTPException(status_code=404, detail=f"Strategy '{strategy_name}' not found")
    return config.to_dict()

@app.post("/api/auth/telegram")
async def telegram_auth(data: TelegramAuthData):
    """Authenticate via Telegram WebApp"""
    result = verify_telegram_webapp(data.init_data)
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid Telegram authentication")
    
    user = result["user"]
    telegram_id = user.get("id")
    
    token = session_manager.create_session(telegram_id, user)
    strategy = session_manager.get_strategy(telegram_id)
    deriv_token = session_manager.get_deriv_token(telegram_id)
    deriv_account = session_manager.get_deriv_account(telegram_id)
    
    return {
        "success": True,
        "token": token,
        "user": user,
        "selected_strategy": strategy,
        "deriv_connected": deriv_token is not None,
        "deriv_account": deriv_account
    }

@app.post("/api/telegram/get-deriv-token")
async def get_deriv_token_for_telegram(data: TelegramAuthData):
    """Get Deriv token - requires valid Telegram WebApp initData for security"""
    result = verify_telegram_webapp(data.init_data)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid Telegram authentication")
    
    user = result.get("user", {})
    telegram_id = user.get("id")
    if not telegram_id:
        raise HTTPException(status_code=400, detail="Invalid user data")
    
    deriv_token = session_manager.get_deriv_token(telegram_id)
    deriv_account = session_manager.get_deriv_account(telegram_id)
    
    if deriv_token:
        return {
            "success": True, 
            "token": deriv_token,
            "account": deriv_account
        }
    return {"success": False, "error": "Not logged in via Telegram bot"}

@app.get("/api/telegram/check-login")
async def check_telegram_login(telegram_id: int = Query(...)):
    """Check if user has logged in via Telegram bot with Deriv"""
    deriv_token = session_manager.get_deriv_token(telegram_id)
    deriv_account = session_manager.get_deriv_account(telegram_id)
    strategy = session_manager.get_strategy(telegram_id)
    
    if deriv_token and deriv_account:
        return {
            "logged_in": True,
            "connected": True,
            "balance": deriv_account.get("balance", 0),
            "currency": deriv_account.get("currency", "USD"),
            "loginid": deriv_account.get("loginid", ""),
            "account_type": deriv_account.get("account_type", "demo"),
            "strategy": strategy
        }
    
    ws = deriv_connections.get(telegram_id)
    if ws and hasattr(ws, 'is_connected') and ws.is_connected():
        return {
            "logged_in": True,
            "connected": True,
            "balance": ws.get_balance() if hasattr(ws, 'get_balance') else 0,
            "currency": ws.get_currency() if hasattr(ws, 'get_currency') else "USD",
            "loginid": ws.loginid if hasattr(ws, 'loginid') else "",
            "account_type": ws.account_type if hasattr(ws, 'account_type') else "demo",
            "strategy": strategy
        }
    
    return {"logged_in": False, "connected": False}

@app.post("/api/telegram/sync-deriv-token")
async def sync_deriv_token(session_token: str = Query(...), deriv_token: str = Query(...)):
    """Sync Deriv token from webapp to server - requires valid session"""
    session = session_manager.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    session_manager.set_deriv_token(telegram_id, deriv_token)
    logger.info(f"Deriv token synced for telegram_id: {telegram_id}")
    return {"success": True}

@app.post("/api/telegram/sync-deriv-account")
async def sync_deriv_account(request: Request, session_token: str = Query(...)):
    """Sync Deriv account info from webapp to server - requires valid session"""
    session = session_manager.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    try:
        account_data = await request.json()
        session_manager.set_deriv_account(telegram_id, account_data)
        logger.info(f"Deriv account synced for telegram_id: {telegram_id}")
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/user/strategy")
async def get_user_strategy(token: str = Query(...)):
    """Get user's selected strategy"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    strategy = session_manager.get_strategy(telegram_id)
    
    return {"strategy": strategy}

@app.post("/api/telegram/set-strategy")
async def telegram_set_strategy(telegram_id: int = Query(...), strategy: str = Query(...)):
    """Set strategy from Telegram bot - no session required"""
    session_manager.set_strategy(telegram_id, strategy)
    logger.info(f"Strategy for user {telegram_id} has been successfully set to {strategy}.")
    
    strategy_routes = {
        "TERMINAL": "/terminal",
        "TICK_PICKER": "/tick-picker",
        "DIGITPAD": "/digitpad",
        "AMT": "/amt",
        "SNIPER": "/sniper",
        "LDP": "/digitpad",
        "MULTI_INDICATOR": "/terminal"
    }
    route = strategy_routes.get(strategy, "/terminal")
    
    logger.info(f"Strategy set via Telegram for user {telegram_id}: {strategy}")
    return {"success": True, "telegram_id": telegram_id, "strategy": strategy, "route": route}

@app.get("/api/telegram/get-strategy")
async def telegram_get_strategy(telegram_id: int = Query(...)):
    """Get strategy and route for a telegram user"""
    strategy = session_manager.get_strategy(telegram_id)
    
    strategy_routes = {
        "TERMINAL": "/terminal",
        "TICK_PICKER": "/tick-picker",
        "DIGITPAD": "/digitpad",
        "AMT": "/amt",
        "SNIPER": "/sniper",
        "LDP": "/digitpad",
        "MULTI_INDICATOR": "/terminal"
    }
    
    if strategy:
        route = strategy_routes.get(strategy, "/terminal")
        return {"strategy": strategy, "route": route}
    return {"strategy": None, "route": None}

@app.post("/api/user/strategy")
async def set_user_strategy(token: str = Query(...), strategy: str = Query(...)):
    """Set user's selected strategy"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    session_manager.set_strategy(telegram_id, strategy)
    
    return {"success": True, "strategy": strategy}

@app.get("/api/summary")
async def get_summary(token: str = Query(...)):
    """Get trading summary"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    ws = deriv_connections.get(telegram_id)
    deriv_account = session_manager.get_deriv_account(telegram_id)
    
    if deriv_account:
        return {
            "balance": deriv_account.get("balance", 0),
            "currency": deriv_account.get("currency", "USD"),
            "connected": True,
            "selected_strategy": session_manager.get_strategy(telegram_id)
        }
    
    return {
        "balance": ws.get_balance() if ws and hasattr(ws, 'get_balance') and ws.is_connected() else 0,
        "currency": ws.get_currency() if ws and hasattr(ws, 'get_currency') and ws.is_connected() else "USD",
        "connected": ws.is_connected() if ws and hasattr(ws, 'is_connected') else False,
        "selected_strategy": session_manager.get_strategy(telegram_id)
    }

@app.post("/api/trade/place")
async def place_trade(trade: TradeRequest, token: str = Query(...)):
    """Place a manual trade"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    ws = deriv_connections.get(telegram_id)
    
    if not ws or not ws.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to Deriv")
    
    contract_type = trade.contract_type
    if not contract_type:
        contract_type = "CALL" if trade.direction == "BUY" else "PUT"
    
    result = ws.buy_contract(
        contract_type=contract_type,
        symbol=trade.symbol,
        stake=trade.stake,
        duration=trade.duration,
        duration_unit=trade.duration_unit,
        barrier=trade.barrier
    )
    
    if result:
        return {"success": True, "contract": result}
    else:
        raise HTTPException(status_code=400, detail="Trade failed")

@app.post("/api/auto-trade/start")
async def start_auto_trade(config: AutoTradeConfig, token: str = Query(...)):
    """Start auto trading for a strategy"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    ws = deriv_connections.get(telegram_id)
    
    if not ws or not ws.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to Deriv")
    
    session_manager.set_strategy(telegram_id, config.strategy)
    
    return {
        "success": True,
        "message": f"Auto trading started with {config.strategy}",
        "config": config.dict()
    }

@app.post("/api/auto-trade/stop")
async def stop_auto_trade(token: str = Query(...)):
    """Stop auto trading"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    return {"success": True, "message": "Auto trading stopped"}

@app.get("/api/strategy/{strategy_name}/stats")
async def get_strategy_stats(strategy_name: str, token: str = Query(...)):
    """Get statistics for a strategy"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    strategy = strategy_instances.get(strategy_name)
    if not strategy:
        return {"wins": 0, "losses": 0, "profit": 0, "win_rate": 0}
    
    if hasattr(strategy, "get_stats"):
        return strategy.get_stats()
    elif hasattr(strategy, "get_all_stats"):
        return strategy.get_all_stats()
    
    return {"wins": 0, "losses": 0, "profit": 0, "win_rate": 0}


# ==================== Trading Control API ====================

@app.post("/api/trading/start")
async def trading_start(request: TradingStartRequest):
    """
    Start trading for a user via API
    Reuses existing trading_manager from telegram_bot if available
    Auto-reconnects to Deriv if connection is missing/disconnected but token exists
    """
    telegram_id = request.telegram_id
    
    # Check if already trading
    existing_manager = trading_managers.get(telegram_id)
    if existing_manager and existing_manager.state == TradingState.RUNNING:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "Trading already running for this user",
                "message": "Trading already running for this user",
                "status": existing_manager.get_status()
            }
        )
    
    # Get Deriv WebSocket connection for user
    ws = deriv_connections.get(telegram_id)
    
    # Auto-reconnect logic: If no connection or disconnected, try to reconnect using stored token
    if not ws or not ws.is_connected():
        # Check if we have a stored Deriv token for this user
        stored_token = session_manager.get_deriv_token(telegram_id)
        
        if stored_token:
            logger.info(f"Auto-reconnecting to Deriv for telegram_id: {telegram_id}")
            try:
                from deriv_ws import DerivWebSocket
                
                # Create new WebSocket connection
                new_ws = DerivWebSocket()
                
                if new_ws.connect():
                    success, error_msg = new_ws.authorize(stored_token)
                    
                    if success:
                        # Register the new connection
                        deriv_connections[telegram_id] = new_ws
                        ws = new_ws
                        
                        # Sync account info
                        account_data = {
                            "balance": new_ws.get_balance() if hasattr(new_ws, 'get_balance') else 0,
                            "currency": new_ws.get_currency() if hasattr(new_ws, 'get_currency') else "USD",
                            "loginid": new_ws.loginid if hasattr(new_ws, 'loginid') else "",
                            "account_type": new_ws.account_type if hasattr(new_ws, 'account_type') else "demo"
                        }
                        session_manager.set_deriv_account(telegram_id, account_data)
                        logger.info(f"Auto-reconnected to Deriv for telegram_id: {telegram_id}")
                    else:
                        new_ws.disconnect()
                        logger.error(f"Auto-reconnect authorization failed for telegram_id: {telegram_id}: {error_msg}")
                        return JSONResponse(
                            status_code=400,
                            content={
                                "success": False,
                                "error": f"Failed to reconnect: {error_msg}. Please re-login via Telegram bot.",
                                "message": f"Failed to reconnect: {error_msg}. Please re-login via Telegram bot."
                            }
                        )
                else:
                    logger.error(f"Auto-reconnect WebSocket connection failed for telegram_id: {telegram_id}")
                    return JSONResponse(
                        status_code=400,
                        content={
                            "success": False,
                            "error": "Failed to connect to Deriv. Please try again or re-login via Telegram bot.",
                            "message": "Failed to connect to Deriv. Please try again or re-login via Telegram bot."
                        }
                    )
            except Exception as e:
                logger.error(f"Auto-reconnect error for telegram_id {telegram_id}: {e}")
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "error": f"Connection error: {str(e)}. Please re-login via Telegram bot.",
                        "message": f"Connection error: {str(e)}. Please re-login via Telegram bot."
                    }
                )
        else:
            # No stored token - user must login via Telegram
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": "Not connected to Deriv. Please login via Telegram bot first.",
                    "message": "Not connected to Deriv. Please login via Telegram bot first."
                }
            )
    
    # Map strategy string to StrategyType enum
    strategy_map = {
        "TERMINAL": StrategyType.TERMINAL,
        "TICK_PICKER": StrategyType.TICK_PICKER,
        "DIGITPAD": StrategyType.DIGITPAD,
        "AMT": StrategyType.AMT,
        "SNIPER": StrategyType.SNIPER,
        "LDP": StrategyType.LDP,
        "MULTI_INDICATOR": StrategyType.MULTI_INDICATOR,
    }
    
    strategy_type = strategy_map.get(request.strategy.upper())
    if not strategy_type:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": f"Invalid strategy: {request.strategy}. Valid strategies: {list(strategy_map.keys())}",
                "message": f"Invalid strategy: {request.strategy}. Valid strategies: {list(strategy_map.keys())}"
            }
        )
    
    # Create trading config
    config = TradingConfig(
        symbol=request.symbol,
        strategy=strategy_type,
        base_stake=request.stake,
        target_trades=request.target_trades if request.target_trades != -1 else 999999,
        auto_trade=True
    )
    
    # Create or reuse trading manager
    if existing_manager:
        existing_manager.update_config(config)
        trading_manager = existing_manager
    else:
        trading_manager = TradingManager(ws, config)
        register_trading_manager(telegram_id, trading_manager)
    
    # Update strategy in session manager
    session_manager.set_strategy(telegram_id, request.strategy.upper())
    
    # Start trading
    success = trading_manager.start()
    
    if success:
        logger.info(f"Trading started via API for telegram_id: {telegram_id}, symbol: {request.symbol}, strategy: {request.strategy}")
        return {
            "success": True,
            "message": f"Trading started with {request.strategy} on {request.symbol}",
            "status": trading_manager.get_status()
        }
    else:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "Failed to start trading. Check if WebSocket is connected and configured.",
                "message": "Failed to start trading. Check if WebSocket is connected and configured.",
                "status": trading_manager.get_status()
            }
        )


@app.post("/api/trading/stop")
async def trading_stop(request: TradingStopRequest):
    """
    Stop trading for a user via API
    """
    telegram_id = request.telegram_id
    
    trading_manager = trading_managers.get(telegram_id)
    if not trading_manager:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "No active trading session found for this user"
            }
        )
    
    if trading_manager.state == TradingState.IDLE:
        return {
            "success": True,
            "message": "Trading already stopped"
        }
    
    # Stop trading
    trading_manager.stop()
    
    logger.info(f"Trading stopped via API for telegram_id: {telegram_id}")
    return {
        "success": True,
        "message": "Trading stopped successfully"
    }


@app.get("/api/trading/status")
async def trading_status(telegram_id: int = Query(...)):
    """
    Get real-time trading status for a user
    """
    trading_manager = trading_managers.get(telegram_id)
    
    # Get base account info
    ws = deriv_connections.get(telegram_id)
    deriv_account = session_manager.get_deriv_account(telegram_id)
    strategy = session_manager.get_strategy(telegram_id)
    
    # Calculate balance from deriv account or ws connection
    balance = 0.0
    if deriv_account:
        balance = deriv_account.get("balance", 0)
    elif ws and hasattr(ws, 'get_balance') and ws.is_connected():
        balance = ws.get_balance()
    
    if not trading_manager:
        # No trading manager - return idle status
        return {
            "success": True,
            "is_running": False,
            "total_trades": 0,
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "profit": 0.0,
            "win_rate": 0.0,
            "balance": balance,
            "symbol": "",
            "strategy": strategy or ""
        }
    
    # Get status from trading manager
    status = trading_manager.get_status()
    total_trades = status.get("trades", 0)
    wins = status.get("wins", 0)
    losses = status.get("losses", 0)
    
    return {
        "success": True,
        "is_running": status.get("state") == TradingState.RUNNING.value,
        "total_trades": total_trades,
        "trades": total_trades,
        "wins": wins,
        "losses": losses,
        "profit": status.get("session_profit", status.get("profit", 0.0)),
        "win_rate": status.get("win_rate", 0.0),
        "balance": status.get("balance", balance),
        "symbol": status.get("symbol", ""),
        "strategy": status.get("strategy", strategy or "")
    }


@app.get("/api/debug")
async def get_debug_info(telegram_id: int = Query(None)):
    """
    Get debug information including connection metrics and trading state.
    Used for troubleshooting timeout and connection issues.
    """
    debug_info = {
        "server_time": datetime.now().isoformat(),
        "active_websocket_connections": manager.get_connection_count(),
        "active_trading_managers": len(trading_managers),
        "active_deriv_connections": len(deriv_connections)
    }
    
    if telegram_id:
        tm = trading_managers.get(telegram_id)
        ws = deriv_connections.get(telegram_id)
        
        debug_info["user"] = {
            "telegram_id": telegram_id,
            "has_trading_manager": tm is not None,
            "has_deriv_connection": ws is not None
        }
        
        if tm and hasattr(tm, 'get_debug_info'):
            debug_info["trading_debug"] = tm.get_debug_info()
        
        if ws and hasattr(ws, 'get_connection_metrics'):
            debug_info["connection_metrics"] = ws.get_connection_metrics()
    
    all_manager_states = {}
    for uid, tm in trading_managers.items():
        all_manager_states[uid] = {
            "state": tm.state.value if hasattr(tm, 'state') else "unknown",
            "trades": tm.session_trades if hasattr(tm, 'session_trades') else 0,
            "pending_result": tm.pending_result if hasattr(tm, 'pending_result') else False
        }
    
    debug_info["all_trading_managers"] = all_manager_states
    
    return debug_info


@app.get("/api/deriv/account")
async def get_deriv_account_info(telegram_id: int = Query(...)):
    """Get Deriv account info for a user"""
    deriv_account = session_manager.get_deriv_account(telegram_id)
    if deriv_account:
        return deriv_account
    
    ws = deriv_connections.get(telegram_id)
    if ws and hasattr(ws, 'is_connected') and ws.is_connected():
        return {
            "balance": ws.get_balance() if hasattr(ws, 'get_balance') else 0,
            "currency": ws.get_currency() if hasattr(ws, 'get_currency') else "USD",
            "loginid": ws.loginid if hasattr(ws, 'loginid') else "",
            "account_type": ws.account_type if hasattr(ws, 'account_type') else "demo"
        }
    
    return {"error": "No account connected"}


# ==================== WebSocket ====================

@app.websocket("/ws/stream")
async def websocket_endpoint(
    websocket: WebSocket, 
    token: str = Query(None),
    telegram_id: int = Query(None)
):
    """WebSocket for real-time updates - accepts token OR telegram_id for auth"""
    user_id = None
    resolved_telegram_id = None
    
    # Try token-based authentication first
    if token:
        session = session_manager.get_session(token)
        if session:
            user_id = session.get("user_id")
            resolved_telegram_id = session.get("telegram_id")
    
    # Fallback to telegram_id direct authentication
    if not user_id and telegram_id:
        user_id = str(telegram_id)
        resolved_telegram_id = telegram_id
    
    # Reject if no valid authentication
    if not user_id:
        await websocket.close(code=4001)
        return
    
    await manager.connect(websocket, user_id, resolved_telegram_id)
    
    try:
        strategy = session_manager.get_strategy(resolved_telegram_id)
        ws = deriv_connections.get(resolved_telegram_id)
        deriv_account = session_manager.get_deriv_account(resolved_telegram_id)
        
        snapshot_data = {
            "connected": False,
            "balance": 0,
            "currency": "USD",
            "selected_strategy": strategy
        }
        
        if deriv_account:
            snapshot_data.update({
                "connected": True,
                "balance": deriv_account.get("balance", 0),
                "currency": deriv_account.get("currency", "USD"),
                "loginid": deriv_account.get("loginid", ""),
                "account_type": deriv_account.get("account_type", "demo")
            })
        elif ws and hasattr(ws, 'is_connected') and ws.is_connected():
            snapshot_data.update({
                "connected": True,
                "balance": ws.get_balance() if hasattr(ws, 'get_balance') else 0,
                "currency": ws.get_currency() if hasattr(ws, 'get_currency') else "USD",
                "loginid": ws.loginid if hasattr(ws, 'loginid') else "",
                "account_type": ws.account_type if hasattr(ws, 'account_type') else "demo"
            })
        
        await websocket.send_json({
            "type": "snapshot",
            "data": snapshot_data
        })
        
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "set_strategy":
                new_strategy = data.get("strategy")
                session_manager.set_strategy(resolved_telegram_id, new_strategy)
                manager.set_strategy(user_id, new_strategy)
                
                await websocket.send_json({
                    "type": "strategy_changed",
                    "strategy": new_strategy
                })
            
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif data.get("type") == "sync_account":
                account_data = data.get("data", {})
                session_manager.set_deriv_account(resolved_telegram_id, account_data)
                await websocket.send_json({"type": "account_synced", "success": True})
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)


# ==================== Helper Functions ====================

def register_deriv_connection(telegram_id: int, ws_connection):
    """Register a Deriv WebSocket connection for a user"""
    deriv_connections[telegram_id] = ws_connection
    logger.info(f"Registered Deriv connection for telegram_id: {telegram_id}")
    
    # Sync account info to session_manager for WebApp auto-connect
    try:
        if hasattr(ws_connection, 'is_connected') and ws_connection.is_connected():
            account_data = {
                "balance": ws_connection.get_balance() if hasattr(ws_connection, 'get_balance') else 0,
                "currency": ws_connection.get_currency() if hasattr(ws_connection, 'get_currency') else "USD",
                "loginid": ws_connection.loginid if hasattr(ws_connection, 'loginid') else "",
                "account_type": ws_connection.account_type if hasattr(ws_connection, 'account_type') else "demo"
            }
            session_manager.set_deriv_account(telegram_id, account_data)
            logger.info(f"Synced account info to session_manager for telegram_id: {telegram_id}")
    except Exception as e:
        logger.error(f"Failed to sync account info for telegram_id {telegram_id}: {e}")

def unregister_deriv_connection(telegram_id: int):
    """Unregister a Deriv WebSocket connection for a user"""
    deriv_connections.pop(telegram_id, None)
    logger.info(f"Unregistered Deriv connection for telegram_id: {telegram_id}")

def register_strategy_instance(name: str, instance):
    """Register a strategy instance"""
    strategy_instances[name] = instance
    logger.info(f"Registered strategy: {name}")

def register_trading_manager(telegram_id: int, trading_manager):
    """Register a TradingManager instance for a user - callable from telegram_bot"""
    trading_managers[telegram_id] = trading_manager
    logger.info(f"Registered trading manager for telegram_id: {telegram_id}")

def unregister_trading_manager(telegram_id: int):
    """Unregister a TradingManager instance for a user - callable from telegram_bot"""
    trading_managers.pop(telegram_id, None)
    logger.info(f"Unregistered trading manager for telegram_id: {telegram_id}")

def get_trading_manager(telegram_id: int):
    """Get TradingManager for a user"""
    return trading_managers.get(telegram_id)


# ==================== Run Server ====================

def run_server(host: str = "0.0.0.0", port: int = 5000):
    """Run the FastAPI server"""
    uvicorn.run(app, host=host, port=port, log_level="info")

def start_server_thread(host: str = "0.0.0.0", port: int = 5000):
    """Start server in a separate thread"""
    thread = threading.Thread(target=run_server, args=(host, port), daemon=True)
    thread.start()
    logger.info(f"Web server started on {host}:{port}")
    return thread


if __name__ == "__main__":
    run_server()
