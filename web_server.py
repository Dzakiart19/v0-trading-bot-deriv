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


# ==================== WebSocket Manager ====================

class ConnectionManager:
    """Manage WebSocket connections"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_strategies: Dict[str, str] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"WebSocket connected: {user_id}")
    
    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
        logger.info(f"WebSocket disconnected: {user_id}")
    
    async def send_personal(self, user_id: str, data: dict):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(data)
            except:
                self.disconnect(user_id)
    
    async def broadcast(self, data: dict):
        for user_id, ws in list(self.active_connections.items()):
            try:
                await ws.send_json(data)
            except:
                self.disconnect(user_id)
    
    def set_strategy(self, user_id: str, strategy: str):
        self.user_strategies[user_id] = strategy
    
    def get_strategy(self, user_id: str) -> Optional[str]:
        return self.user_strategies.get(user_id)


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


# ==================== Global State ====================

manager = ConnectionManager()
session_manager = WebSessionManager()

strategy_instances: Dict[str, Any] = {}
deriv_connections: Dict[int, Any] = {}

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DERIV_APP_ID = os.environ.get("DERIV_APP_ID", "1089")


# ==================== FastAPI App ====================

app = FastAPI(title="Deriv Trading Bot API", version="2.0")

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


# ==================== Telegram WebApp Auth ====================

def verify_telegram_webapp(init_data: str) -> Optional[Dict]:
    """Verify Telegram WebApp init data"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return None
    
    try:
        params = dict(p.split("=") for p in init_data.split("&") if "=" in p)
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
        
        if calculated_hash != received_hash:
            logger.error("Invalid Telegram WebApp hash")
            return None
        
        import urllib.parse
        user_str = urllib.parse.unquote(params.get("user", "{}"))
        user_data = json.loads(user_str)
        
        return {
            "user": user_data,
            "auth_date": params.get("auth_date"),
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
    logger.info(f"Strategy set via Telegram for user {telegram_id}: {strategy}")
    return {"success": True, "telegram_id": telegram_id, "strategy": strategy}

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
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    """WebSocket for real-time updates"""
    session = session_manager.get_session(token)
    if not session:
        await websocket.close(code=4001)
        return
    
    user_id = session.get("user_id")
    telegram_id = session.get("telegram_id")
    
    await manager.connect(websocket, user_id)
    
    try:
        strategy = session_manager.get_strategy(telegram_id)
        ws = deriv_connections.get(telegram_id)
        deriv_account = session_manager.get_deriv_account(telegram_id)
        
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
                session_manager.set_strategy(telegram_id, new_strategy)
                manager.set_strategy(user_id, new_strategy)
                
                await websocket.send_json({
                    "type": "strategy_changed",
                    "strategy": new_strategy
                })
            
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            
            elif data.get("type") == "sync_account":
                account_data = data.get("data", {})
                session_manager.set_deriv_account(telegram_id, account_data)
                await websocket.send_json({"type": "account_synced", "success": True})
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)


# ==================== Helper Functions ====================

def register_deriv_connection(telegram_id: int, ws_connection):
    """Register a Deriv WebSocket connection for a user"""
    deriv_connections[telegram_id] = ws_connection
    logger.info(f"Registered Deriv connection for telegram_id: {telegram_id}")

def unregister_deriv_connection(telegram_id: int):
    """Unregister a Deriv WebSocket connection for a user"""
    deriv_connections.pop(telegram_id, None)
    logger.info(f"Unregistered Deriv connection for telegram_id: {telegram_id}")

def register_strategy_instance(name: str, instance):
    """Register a strategy instance"""
    strategy_instances[name] = instance
    logger.info(f"Registered strategy: {name}")


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
