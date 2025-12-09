"""
Web Server - FastAPI with WebSocket and multi-strategy WebApps
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
    direction: str  # BUY or SELL
    stake: float
    duration: int = 5
    duration_unit: str = "t"
    
class AutoTradeConfig(BaseModel):
    symbol: str
    strategy: str
    base_stake: float = 1.0
    target_trades: int = 10


# ==================== WebSocket Manager ====================

class ConnectionManager:
    """Manage WebSocket connections"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_strategies: Dict[str, str] = {}  # user_id -> selected strategy
    
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
        self.sessions: Dict[str, Dict] = {}  # session_token -> {user_id, telegram_id, ...}
        self.telegram_to_session: Dict[int, str] = {}  # telegram_user_id -> session_token
        self.user_strategy: Dict[int, str] = {}  # telegram_user_id -> selected_strategy
    
    def create_session(self, telegram_user_id: int, user_data: dict) -> str:
        """Create session from Telegram auth"""
        # Check existing session
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
        """Set selected strategy for user"""
        self.user_strategy[telegram_id] = strategy
    
    def get_strategy(self, telegram_id: int) -> Optional[str]:
        """Get selected strategy for user"""
        return self.user_strategy.get(telegram_id)
    
    def invalidate(self, token: str):
        session = self.sessions.pop(token, None)
        if session:
            self.telegram_to_session.pop(session.get("telegram_id"), None)


# ==================== Global State ====================

manager = ConnectionManager()
session_manager = WebSessionManager()

# Strategy instances (will be initialized by main.py)
strategy_instances: Dict[str, Any] = {}
deriv_connections: Dict[int, Any] = {}  # telegram_id -> DerivWebSocket

# Bot token for verification
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


# ==================== FastAPI App ====================

app = FastAPI(title="Deriv Trading Bot API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Static WebApp Routes ====================

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve main index page from webapps folder"""
    with open("webapps/index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/terminal", response_class=HTMLResponse)
async def serve_terminal():
    """Serve Terminal strategy page"""
    with open("webapps/terminal.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/tick-picker", response_class=HTMLResponse)
async def serve_tick_picker():
    """Serve Tick Picker strategy page"""
    with open("webapps/tick-picker.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/digitpad", response_class=HTMLResponse)
async def serve_digitpad():
    """Serve DigitPad strategy page"""
    with open("webapps/digitpad.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/amt", response_class=HTMLResponse)
async def serve_amt():
    """Serve AMT Accumulator strategy page"""
    with open("webapps/amt.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/sniper", response_class=HTMLResponse)
async def serve_sniper():
    """Serve Sniper strategy page"""
    with open("webapps/sniper.html", "r") as f:
        return HTMLResponse(content=f.read())


# ==================== Telegram WebApp Auth ====================

def verify_telegram_webapp(init_data: str) -> Optional[Dict]:
    """Verify Telegram WebApp init data"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not configured")
        return None
    
    try:
        # Parse init_data
        params = dict(p.split("=") for p in init_data.split("&") if "=" in p)
        
        # Get hash
        received_hash = params.pop("hash", "")
        
        # Sort and create data check string
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        
        # Calculate secret key
        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()
        
        # Calculate hash
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if calculated_hash != received_hash:
            logger.error("Invalid Telegram WebApp hash")
            return None
        
        # Parse user data
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


@app.post("/api/auth/telegram")
async def telegram_auth(data: TelegramAuthData):
    """Authenticate via Telegram WebApp"""
    result = verify_telegram_webapp(data.init_data)
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid Telegram authentication")
    
    user = result["user"]
    telegram_id = user.get("id")
    
    # Create session
    token = session_manager.create_session(telegram_id, user)
    
    # Get selected strategy
    strategy = session_manager.get_strategy(telegram_id)
    
    return {
        "success": True,
        "token": token,
        "user": user,
        "selected_strategy": strategy
    }


@app.get("/api/user/strategy")
async def get_user_strategy(token: str = Query(...)):
    """Get user's selected strategy"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    telegram_id = session.get("telegram_id")
    strategy = session_manager.get_strategy(telegram_id)
    
    return {"strategy": strategy}


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
    
    # Get Deriv connection if exists
    ws = deriv_connections.get(telegram_id)
    
    return {
        "balance": ws.get_balance() if ws and ws.is_connected() else 0,
        "currency": ws.get_currency() if ws and ws.is_connected() else "USD",
        "connected": ws.is_connected() if ws else False,
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
    
    # Map direction to contract type
    contract_type = "CALL" if trade.direction == "BUY" else "PUT"
    
    result = ws.buy_contract(
        contract_type=contract_type,
        symbol=trade.symbol,
        stake=trade.stake,
        duration=trade.duration,
        duration_unit=trade.duration_unit
    )
    
    if result:
        return {"success": True, "contract": result}
    else:
        raise HTTPException(status_code=400, detail="Trade failed")


@app.get("/api/strategy/{strategy_name}/stats")
async def get_strategy_stats(strategy_name: str, token: str = Query(...)):
    """Get statistics for a strategy"""
    session = session_manager.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    strategy = strategy_instances.get(strategy_name)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    if hasattr(strategy, "get_stats"):
        return strategy.get_stats()
    elif hasattr(strategy, "get_all_stats"):
        return strategy.get_all_stats()
    
    return {}


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
        # Send initial snapshot
        strategy = session_manager.get_strategy(telegram_id)
        ws = deriv_connections.get(telegram_id)
        
        await websocket.send_json({
            "type": "snapshot",
            "data": {
                "connected": ws.is_connected() if ws else False,
                "balance": ws.get_balance() if ws and ws.is_connected() else 0,
                "currency": ws.get_currency() if ws and ws.is_connected() else "USD",
                "selected_strategy": strategy
            }
        })
        
        # Listen for messages
        while True:
            data = await websocket.receive_json()
            
            # Handle strategy change
            if data.get("type") == "set_strategy":
                new_strategy = data.get("strategy")
                session_manager.set_strategy(telegram_id, new_strategy)
                manager.set_strategy(user_id, new_strategy)
                
                await websocket.send_json({
                    "type": "strategy_changed",
                    "strategy": new_strategy
                })
            
            # Handle ping
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        manager.disconnect(user_id)


            padding: 16px 0;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 20px;
        }}
        .logo {{ 
            font-size: 1.5rem; 
            font-weight: bold; 
            color: var(--accent-green);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .status {{ 
            display: flex; 
            align-items: center; 
            gap: 8px;
            font-size: 0.875rem;
            color: var(--text-secondary);
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--accent-red);
        }}
        .status-dot.connected {{ background: var(--accent-green); }}
        .btn {{
            padding: 12px 24px;
            border-radius: 8px;
            border: none;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 1rem;
        }}
        .btn-primary {{
            background: var(--accent-green);
            color: var(--bg-primary);
        }}
        .btn-primary:hover {{ opacity: 0.9; }}
        .btn-danger {{ background: var(--accent-red); color: white; }}
        .btn-secondary {{ 
            background: transparent; 
            border: 1px solid var(--border-color);
            color: var(--text-primary);
        }}
        .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }}
        .card-title {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .card-value {{
            font-size: 1.75rem;
            font-weight: bold;
        }}
        .card-value.green {{ color: var(--accent-green); }}
        .card-value.red {{ color: var(--accent-red); }}
        .card-value.blue {{ color: var(--accent-blue); }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }}
        .input-group {{
            margin-bottom: 16px;
        }}
        .input-group label {{
            display: block;
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 6px;
        }}
        .input-group input, .input-group select {{
            width: 100%;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            font-size: 1rem;
        }}
        .input-group input:focus, .input-group select:focus {{
            outline: none;
            border-color: var(--accent-green);
        }}
        .toggle {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            background: var(--bg-secondary);
            border-radius: 8px;
            margin-bottom: 12px;
        }}
        .toggle-switch {{
            width: 48px;
            height: 24px;
            background: var(--border-color);
            border-radius: 12px;
            position: relative;
            cursor: pointer;
            transition: background 0.2s;
        }}
        .toggle-switch.active {{ background: var(--accent-green); }}
        .toggle-switch::after {{
            content: '';
            position: absolute;
            width: 20px;
            height: 20px;
            background: white;
            border-radius: 50%;
            top: 2px;
            left: 2px;
            transition: transform 0.2s;
        }}
        .toggle-switch.active::after {{ transform: translateX(24px); }}
        .console {{
            background: #000;
            border-radius: 8px;
            padding: 16px;
            font-family: 'Courier New', monospace;
            font-size: 0.875rem;
            height: 200px;
            overflow-y: auto;
            margin-top: 16px;
        }}
        .console-line {{
            color: var(--accent-green);
            margin-bottom: 4px;
        }}
        .console-line.error {{ color: var(--accent-red); }}
        .console-line.info {{ color: var(--accent-blue); }}
        .chart-container {{
            background: var(--bg-secondary);
            border-radius: 8px;
            padding: 16px;
            height: 250px;
            position: relative;
        }}
        .loading {{
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-secondary);
        }}
        .hidden {{ display: none !important; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .pulse {{ animation: pulse 1.5s infinite; }}
    </style>
    {extra_styles}
</head>
<body>
    <div class="container">
        {content}
    </div>
    <script>
        // Telegram WebApp integration
        const tg = window.Telegram.WebApp;
        tg.expand();
        tg.ready();
        
        // Get init data and user
        const initData = tg.initData;
        const tgUser = tg.initDataUnsafe?.user;
        const telegramId = tgUser?.id;
        
        let authToken = null;
        let ws = null;
        let isConnected = false;
        let derivAppId = '1089';
        let derivWs = null;
        let currentStrategy = null;
        
        // API base URL
        const API_BASE = window.location.origin;
        
        // Get Deriv App ID from server
        async function getDerivAppId() {{
            try {{
                const resp = await fetch(API_BASE + '/api/deriv/app-id');
                const data = await resp.json();
                derivAppId = data.app_id || '1089';
            }} catch (e) {{
                console.error('Failed to get app id:', e);
            }}
        }}
        
        // Check if user is already logged in via Telegram bot
        async function checkTelegramLogin() {{
            if (!telegramId) return false;
            
            try {{
                const resp = await fetch(API_BASE + '/api/telegram/check-login?telegram_id=' + telegramId);
                const data = await resp.json();
                
                if (data.logged_in && data.connected) {{
                    currentStrategy = data.strategy;
                    onDerivConnected({{
                        balance: data.balance,
                        currency: data.currency,
                        loginid: data.loginid,
                        account_type: data.account_type
                    }});
                    return true;
                }}
                return false;
            }} catch (e) {{
                console.error('Check login error:', e);
                return false;
            }}
        }}
        
        // Auth with backend
        async function authenticate() {{
            try {{
                const resp = await fetch(API_BASE + '/api/auth/telegram', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ init_data: initData }})
                }});
                const data = await resp.json();
                if (data.success) {{
                    authToken = data.token;
                    currentStrategy = data.selected_strategy;
                    connectWebSocket();
                    onAuthenticated(data);
                    
                    // Check if already connected via bot
                    const alreadyConnected = await checkTelegramLogin();
                    if (!alreadyConnected) {{
                        logConsole('Login via Telegram bot atau klik tombol Login', 'info');
                    }}
                }}
            }} catch (e) {{
                console.error('Auth error:', e);
                logConsole('Authentication failed', 'error');
            }}
        }}
        
        // WebSocket connection to our server
        function connectWebSocket() {{
            if (!authToken) return;
            ws = new WebSocket(`${{API_BASE.replace('http', 'ws')}}/ws/stream?token=${{authToken}}`);
            
            ws.onopen = () => {{
                isConnected = true;
                updateConnectionStatus(true);
                logConsole('Connected to server', 'info');
            }};
            
            ws.onmessage = (event) => {{
                const msg = JSON.parse(event.data);
                handleWSMessage(msg);
                
                // Handle strategy change from Telegram
                if (msg.type === 'strategy_changed') {{
                    currentStrategy = msg.strategy;
                    onStrategyChanged(msg.strategy);
                }}
                
                // Handle snapshot with Deriv data
                if (msg.type === 'snapshot' && msg.data.connected) {{
                    onDerivConnected(msg.data);
                }}
            }};
            
            ws.onclose = () => {{
                isConnected = false;
                updateConnectionStatus(false);
                logConsole('Disconnected from server', 'error');
                setTimeout(connectWebSocket, 3000);
            }};
        }}
        
        // Connect directly to Deriv (fallback)
        function connectDerivDirect(token) {{
            derivWs = new WebSocket('wss://ws.derivws.com/websockets/v3?app_id=' + derivAppId);
            
            derivWs.onopen = () => {{
                derivWs.send(JSON.stringify({{ authorize: token }}));
            }};
            
            derivWs.onmessage = (msg) => {{
                const data = JSON.parse(msg.data);
                
                if (data.authorize) {{
                    onDerivConnected({{
                        balance: data.authorize.balance,
                        currency: data.authorize.currency,
                        loginid: data.authorize.loginid,
                        account_type: data.authorize.loginid?.includes('VRTC') ? 'demo' : 'real'
                    }});
                    
                    // Sync to server
                    if (telegramId) {{
                        fetch(API_BASE + '/api/telegram/sync-deriv-token?telegram_id=' + telegramId + '&token=' + token, {{
                            method: 'POST'
                        }});
                    }}
                    
                    // Subscribe to balance
                    derivWs.send(JSON.stringify({{ balance: 1, subscribe: 1 }}));
                }}
                
                if (data.balance) {{
                    updateBalance(data.balance.balance, data.balance.currency);
                }}
                
                if (data.tick) {{
                    onTickData(data.tick);
                }}
                
                if (data.error) {{
                    logConsole('Deriv Error: ' + data.error.message, 'error');
                }}
            }};
            
            derivWs.onclose = () => {{
                logConsole('Disconnected from Deriv', 'error');
            }};
        }}
        
        // Called when connected to Deriv (either via bot or direct)
        function onDerivConnected(data) {{
            updateConnectionStatus(true);
            updateBalance(data.balance, data.currency);
            
            const loginBtn = document.getElementById('btn-login');
            if (loginBtn) {{
                loginBtn.textContent = '✓ Connected (' + (data.account_type || 'demo').toUpperCase() + ')';
                loginBtn.disabled = true;
            }}
            
            const statusText = document.getElementById('status-text');
            if (statusText) {{
                statusText.textContent = data.loginid || 'Connected';
            }}
            
            logConsole('Connected to Deriv: ' + (data.loginid || ''), 'info');
        }}
        
        function updateBalance(balance, currency) {{
            const balEl = document.getElementById('balance');
            if (balEl) {{
                balEl.textContent = '$' + parseFloat(balance || 0).toFixed(2);
            }}
        }}
        
        function updateConnectionStatus(connected) {{
            const dot = document.querySelector('.status-dot');
            if (dot) {{
                dot.classList.toggle('connected', connected);
            }}
        }}
        
        function logConsole(msg, type = 'normal') {{
            const consoleEl = document.getElementById('console');
            if (consoleEl) {{
                const line = document.createElement('div');
                line.className = 'console-line ' + type;
                line.textContent = '> ' + new Date().toLocaleTimeString() + ' | ' + msg;
                consoleEl.appendChild(line);
                consoleEl.scrollTop = consoleEl.scrollHeight;
            }}
        }}
        
        // Page-specific handlers (overridden by each page)
        function onAuthenticated(data) {{ console.log('Authenticated', data); }}
        function handleWSMessage(msg) {{ console.log('WS Message', msg); }}
        function onStrategyChanged(strategy) {{ console.log('Strategy changed:', strategy); }}
        function onTickData(tick) {{ console.log('Tick:', tick); }}
        
        // Initialize
        getDerivAppId().then(() => {{
            if (initData) {{
                authenticate();
            }} else {{
                // Fallback for testing outside Telegram
                logConsole('Testing mode - not in Telegram', 'info');
                checkTelegramLogin();
            }}
        }});
    </script>
    {extra_scripts}
</body>
</html>
'''


# Terminal Page
@app.get("/", response_class=HTMLResponse)
@app.get("/terminal", response_class=HTMLResponse)
async def terminal_page():
    content = '''
        <div class="header">
            <div class="logo">
                <span>⚡</span> TERMINAL
            </div>
            <div class="status">
                <div class="status-dot"></div>
                <span id="status-text">Connecting...</span>
            </div>
        </div>
        
        <div class="card" style="background: linear-gradient(135deg, var(--accent-green) 0%, #1a5a2a 100%); border: none;">
            <div style="text-align: center; padding: 16px 0;">
                <div style="font-size: 0.875rem; opacity: 0.8;">SMART ANALYSIS • 80% PROBABILITY</div>
            </div>
        </div>
        
        <button class="btn btn-primary" style="width: 100%; margin-bottom: 20px;" id="btn-login">
            ⚡ LOGIN WITH DERIV
        </button>
        
        <div class="stats-grid">
            <div class="card">
                <div class="card-title">$ BALANCE</div>
                <div class="card-value green" id="balance">$0.00</div>
            </div>
            <div class="card">
                <div class="card-title">📈 P/L</div>
                <div class="card-value" id="pnl">$0.00</div>
            </div>
            <div class="card">
                <div class="card-title">📊 TRADES</div>
                <div class="card-value blue" id="trades">0</div>
            </div>
            <div class="card">
                <div class="card-title">🎯 WIN RATE</div>
                <div class="card-value green" id="winrate">0%</div>
            </div>
        </div>
        
        <div class="card">
            <div class="stats-grid" style="margin-bottom: 16px;">
                <div class="input-group" style="margin-bottom: 0;">
                    <label>STAKE ($)</label>
                    <input type="number" id="stake" value="1" min="0.35" step="0.01">
                </div>
                <div class="input-group" style="margin-bottom: 0;">
                    <label>RISK</label>
                    <select id="risk">
                        <option value="LOW">Low (1.5x)</option>
                        <option value="MEDIUM" selected>Medium (1.8x)</option>
                        <option value="HIGH">High (2.1x)</option>
                        <option value="VERY_HIGH">Very High (2.5x)</option>
                    </select>
                </div>
            </div>
            <div class="stats-grid">
                <div class="input-group" style="margin-bottom: 0;">
                    <label>T/P ($)</label>
                    <input type="number" id="tp" value="5" min="0">
                </div>
                <div class="input-group" style="margin-bottom: 0;">
                    <label>S/L ($)</label>
                    <input type="number" id="sl" value="25" min="0">
                </div>
            </div>
        </div>
        
        <div class="toggle">
            <div>
                <div style="font-weight: 600;">⚡ SMART ANALYSIS</div>
                <div style="font-size: 0.75rem; color: var(--text-secondary);">Trend • Momentum • Patterns</div>
            </div>
            <div class="toggle-switch active" id="toggle-smart" onclick="toggleSmart()"></div>
        </div>
        
        <div class="toggle">
            <div>
                <div style="font-weight: 600;">🔄 HYBRID RECOVERY</div>
                <div style="font-size: 0.75rem; color: var(--text-secondary);">Progressive + Deficit Recovery</div>
            </div>
            <div class="toggle-switch" id="toggle-recovery" onclick="toggleRecovery()"></div>
        </div>
        
        <button class="btn btn-primary" style="width: 100%; margin-top: 16px;" id="btn-start">
            ▶ START TRADING
        </button>
        
        <div class="card" style="margin-top: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div class="card-title" style="margin-bottom: 0;">○ SYSTEM CONSOLE</div>
                <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 0.75rem;" onclick="clearConsole()">CLEAR</button>
            </div>
            <div class="console" id="console">
                <div class="console-line info">> Terminal ready • NEXTERMINAL v9.0</div>
            </div>
        </div>
    '''
    
    extra_scripts = '''
    <script>
        let smartAnalysis = true;
        let hybridRecovery = false;
        let isTrading = false;
        
        function toggleSmart() {
            smartAnalysis = !smartAnalysis;
            document.getElementById('toggle-smart').classList.toggle('active', smartAnalysis);
            logConsole('Smart Analysis: ' + (smartAnalysis ? 'ON' : 'OFF'), 'info');
        }
        
        function toggleRecovery() {
            hybridRecovery = !hybridRecovery;
            document.getElementById('toggle-recovery').classList.toggle('active', hybridRecovery);
            logConsole('Hybrid Recovery: ' + (hybridRecovery ? 'ON' : 'OFF'), 'info');
        }
        
        function clearConsole() {
            document.getElementById('console').innerHTML = '';
        }
        
        document.getElementById('btn-start').addEventListener('click', async () => {
            if (!authToken) {
                logConsole('Please login first', 'error');
                return;
            }
            
            isTrading = !isTrading;
            const btn = document.getElementById('btn-start');
            btn.textContent = isTrading ? '⏹ STOP TRADING' : '▶ START TRADING';
            btn.classList.toggle('btn-danger', isTrading);
            btn.classList.toggle('btn-primary', !isTrading);
            
            if (isTrading) {
                logConsole('Starting Terminal strategy...', 'info');
                // Start auto trading
                try {
                    const resp = await fetch(API_BASE + '/api/autotrade/start?token=' + authToken, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            symbol: 'R_100',
                            strategy: 'TERMINAL',
                            base_stake: parseFloat(document.getElementById('stake').value)
                        })
                    });
                    const data = await resp.json();
                    logConsole('Auto trading started', 'info');
                } catch (e) {
                    logConsole('Failed to start: ' + e.message, 'error');
                }
            } else {
                logConsole('Stopping trading...', 'info');
            }
        });
        
        function onAuthenticated(data) {
            document.getElementById('btn-login').textContent = '✓ CONNECTED';
            document.getElementById('btn-login').disabled = true;
            document.getElementById('status-text').textContent = 'Connected';
            logConsole('Logged in as ' + (data.user.first_name || 'User'), 'info');
        }
        
        function handleWSMessage(msg) {
            if (msg.type === 'snapshot' || msg.type === 'balance_update') {
                document.getElementById('balance').textContent = '$' + (msg.data.balance || 0).toFixed(2);
            }
            if (msg.type === 'trade_result') {
                const won = msg.data.profit > 0;
                logConsole((won ? '✓ WIN' : '✗ LOSS') + ' $' + msg.data.profit.toFixed(2), won ? 'info' : 'error');
            }
            if (msg.type === 'signal') {
                logConsole('Signal: ' + msg.data.direction + ' @ ' + msg.data.confidence + '%', 'info');
            }
        }
    </script>
    '''
    
    return BASE_HTML.format(
        title="Terminal - Deriv Trading",
        extra_styles="",
        content=content,
        extra_scripts=extra_scripts
    )


# Tick Picker Page
@app.get("/tick-picker", response_class=HTMLResponse)
async def tick_picker_page():
    content = '''
        <div class="header">
            <div class="logo">LDP<span style="font-weight: normal; font-size: 1rem;">Tick-Picker</span></div>
            <div class="status">
                <button class="btn btn-primary" style="padding: 8px 16px;" id="btn-login">Login</button>
            </div>
        </div>
        
        <div class="stats-grid" style="grid-template-columns: repeat(3, 1fr);">
            <div class="card" style="text-align: center;">
                <div class="card-title">Account</div>
                <div id="account">********</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">Balance</div>
                <div class="card-value blue" id="balance" style="font-size: 1.25rem;">0.00 USD</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">Profit</div>
                <div class="card-value green" id="profit" style="font-size: 1.25rem;">0.00 USD</div>
            </div>
        </div>
        
        <div class="card">
            <div class="input-group">
                <label>Select Symbol</label>
                <select id="symbol">
                    <option value="R_100">Volatility 100 Index</option>
                    <option value="R_75">Volatility 75 Index</option>
                    <option value="R_50">Volatility 50 Index</option>
                    <option value="R_25">Volatility 25 Index</option>
                    <option value="R_10">Volatility 10 Index</option>
                </select>
            </div>
        </div>
        
        <div class="chart-container">
            <canvas id="tickChart"></canvas>
            <div class="loading" id="chart-loading">
                <span class="pulse">⏳ Analyzing...</span>
            </div>
        </div>
        
        <div class="card" style="text-align: center; margin-top: 16px;">
            <div id="trend-status" style="color: var(--text-secondary);">No active trend detected</div>
            <div style="margin-top: 8px;">
                Ticks(<span id="tick-count">0</span>) | Last Tick: <span id="last-tick">0</span>
            </div>
        </div>
        
        <div class="card">
            <div id="log-area" style="font-size: 0.875rem; color: var(--text-secondary); min-height: 60px;">
                Please log in to your Deriv account to start trading..
            </div>
        </div>
        
        <div class="stats-grid" style="grid-template-columns: 1fr 1fr;">
            <div class="input-group" style="margin-bottom: 0;">
                <label>Stake Type</label>
                <select id="stake-type">
                    <option value="fixed">Fixed Stake</option>
                    <option value="martingale">Martingale</option>
                </select>
            </div>
            <div class="input-group" style="margin-bottom: 0;">
                <label>Amount</label>
                <input type="number" id="stake" value="1.00" min="0.35">
            </div>
        </div>
        
        <div class="stats-grid" style="margin-top: 16px;">
            <button class="btn btn-primary" style="background: #22c55e;" id="btn-buy">↑ BUY</button>
            <button class="btn btn-danger" id="btn-sell">↓ SELL</button>
        </div>
    '''
    
    extra_scripts = '''
    <script>
        let tickData = [];
        let canvas, ctx;
        
        function initChart() {
            canvas = document.getElementById('tickChart');
            ctx = canvas.getContext('2d');
            canvas.width = canvas.parentElement.clientWidth - 32;
            canvas.height = 200;
            document.getElementById('chart-loading').classList.add('hidden');
        }
        
        function drawChart() {
            if (!ctx || tickData.length < 2) return;
            
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            const padding = 20;
            const width = canvas.width - padding * 2;
            const height = canvas.height - padding * 2;
            
            const min = Math.min(...tickData);
            const max = Math.max(...tickData);
            const range = max - min || 1;
            
            ctx.beginPath();
            ctx.strokeStyle = '#58a6ff';
            ctx.lineWidth = 2;
            
            tickData.forEach((price, i) => {
                const x = padding + (i / (tickData.length - 1)) * width;
                const y = padding + height - ((price - min) / range) * height;
                
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            });
            
            ctx.stroke();
            
            // Draw points
            tickData.forEach((price, i) => {
                const x = padding + (i / (tickData.length - 1)) * width;
                const y = padding + height - ((price - min) / range) * height;
                
                ctx.beginPath();
                ctx.arc(x, y, 4, 0, Math.PI * 2);
                ctx.fillStyle = '#58a6ff';
                ctx.fill();
            });
        }
        
        function handleWSMessage(msg) {
            if (msg.type === 'tick') {
                tickData.push(msg.data.quote);
                if (tickData.length > 20) tickData.shift();
                
                document.getElementById('last-tick').textContent = msg.data.quote.toFixed(2);
                document.getElementById('tick-count').textContent = tickData.length;
                
                drawChart();
            }
            if (msg.type === 'snapshot') {
                document.getElementById('balance').textContent = (msg.data.balance || 0).toFixed(2) + ' USD';
            }
        }
        
        function onAuthenticated(data) {
            document.getElementById('btn-login').textContent = '✓ Connected';
            document.getElementById('log-area').textContent = 'Connected! Waiting for tick data...';
            initChart();
        }
        
        document.getElementById('btn-buy').addEventListener('click', async () => {
            if (!authToken) return;
            logConsole('Placing BUY order...', 'info');
            try {
                await fetch(API_BASE + '/api/trade/place?token=' + authToken, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol: document.getElementById('symbol').value,
                        direction: 'BUY',
                        stake: parseFloat(document.getElementById('stake').value),
                        duration: 5,
                        duration_unit: 't'
                    })
                });
            } catch (e) {
                logConsole('Error: ' + e.message, 'error');
            }
        });
        
        document.getElementById('btn-sell').addEventListener('click', async () => {
            if (!authToken) return;
            logConsole('Placing SELL order...', 'info');
            try {
                await fetch(API_BASE + '/api/trade/place?token=' + authToken, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        symbol: document.getElementById('symbol').value,
                        direction: 'SELL',
                        stake: parseFloat(document.getElementById('stake').value),
                        duration: 5,
                        duration_unit: 't'
                    })
                });
            } catch (e) {
                logConsole('Error: ' + e.message, 'error');
            }
        });
        
        function logConsole(msg, type) {
            document.getElementById('log-area').innerHTML += '<br>' + new Date().toLocaleTimeString() + ' | ' + msg;
        }
    </script>
    '''
    
    return BASE_HTML.format(
        title="Tick Picker - Deriv Trading",
        extra_styles="",
        content=content,
        extra_scripts=extra_scripts
    )


# DigitPad Page
@app.get("/digitpad", response_class=HTMLResponse)
async def digitpad_page():
    content = '''
        <div class="header">
            <div class="logo">LDP<span style="font-weight: normal; font-size: 1rem;">Pad</span></div>
            <div class="status">
                <button class="btn btn-primary" style="padding: 8px 16px;" id="btn-login">Login</button>
            </div>
        </div>
        
        <div class="stats-grid" style="grid-template-columns: repeat(3, 1fr);">
            <div class="card" style="text-align: center;">
                <div class="card-title">Account</div>
                <div id="account">********</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">Balance</div>
                <div class="card-value blue" id="balance" style="font-size: 1.25rem;">0.00 USD</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">Profit</div>
                <div class="card-value green" id="profit" style="font-size: 1.25rem;">0.00 USD</div>
            </div>
        </div>
        
        <div class="card" style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 0.875rem;">
                <thead>
                    <tr style="border-bottom: 2px solid var(--border-color);">
                        <th style="padding: 8px; text-align: left;">↓M x D→</th>
                        <th style="padding: 8px; background: #1e3a5f;">0</th>
                        <th style="padding: 8px;">1</th>
                        <th style="padding: 8px;">2</th>
                        <th style="padding: 8px; background: #1e3a5f;">3</th>
                        <th style="padding: 8px;">4</th>
                        <th style="padding: 8px;">5</th>
                        <th style="padding: 8px;">6</th>
                        <th style="padding: 8px;">7</th>
                        <th style="padding: 8px; background: #1e3a5f;">8</th>
                        <th style="padding: 8px;">9</th>
                        <th style="padding: 8px; background: #3b82f6;">Even</th>
                        <th style="padding: 8px; background: #6366f1;">ODD</th>
                    </tr>
                </thead>
                <tbody id="digit-table">
                    <!-- Will be populated by JS -->
                </tbody>
            </table>
        </div>
        
        <div class="stats-grid" style="margin-top: 16px;">
            <div class="card">
                <div id="log-area" style="font-size: 0.875rem; min-height: 80px;">
                    Please log in to your Deriv account to start trading..
                </div>
            </div>
            <div class="card">
                <div class="input-group">
                    <label>Stake</label>
                    <input type="number" id="stake" value="1" min="0.35">
                </div>
                <div style="text-align: center; margin-top: 12px;">
                    <div style="font-weight: bold; margin-bottom: 8px;">Signals Chart</div>
                    <div style="display: flex; justify-content: space-around; font-size: 0.75rem;">
                        <div>
                            <div style="background: #6b7280; padding: 4px 12px; border-radius: 4px;">Differ: 50%</div>
                            <div>Natural</div>
                        </div>
                        <div>
                            <div style="background: #ef4444; padding: 4px 12px; border-radius: 4px;">Differ: 30% (min)</div>
                            <div>Not Good</div>
                        </div>
                        <div>
                            <div style="background: #22c55e; padding: 4px 12px; border-radius: 4px;">Differ: 70% (max)</div>
                            <div>Strong Buy</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    '''
    
    extra_styles = '''
    <style>
        .digit-cell { 
            padding: 8px; 
            text-align: center;
            transition: all 0.2s;
        }
        .digit-cell.hot { background: #22c55e; color: white; }
        .digit-cell.cold { background: #ef4444; color: white; }
        .digit-cell.neutral { background: var(--bg-secondary); }
    </style>
    '''
    
    extra_scripts = '''
    <script>
        const symbols = ['R_10', 'R_25', 'R_50', 'R_75', 'R_100', '1HZ10V', '1HZ25V', '1HZ50V', '1HZ75V', '1HZ100V'];
        const symbolNames = ['10v', '25v', '50v', '75v', '100v', '10(1s)', '25(1s)', '50(1s)', '75(1s)', '100(1s)'];
        let digitData = {};
        
        // Initialize digit data
        symbols.forEach(s => {
            digitData[s] = { counts: Array(10).fill(0), total: 0, even: 0, odd: 0 };
        });
        
        function initTable() {
            const tbody = document.getElementById('digit-table');
            tbody.innerHTML = '';
            
            symbolNames.forEach((name, idx) => {
                const row = document.createElement('tr');
                row.innerHTML = '<td style="padding: 8px; font-weight: bold;">' + name + '</td>';
                
                for (let d = 0; d < 10; d++) {
                    row.innerHTML += '<td class="digit-cell neutral" id="cell-' + idx + '-' + d + '">0</td>';
                }
                
                row.innerHTML += '<td class="digit-cell" style="background: #3b82f6;" id="even-' + idx + '">0</td>';
                row.innerHTML += '<td class="digit-cell" style="background: #6366f1;" id="odd-' + idx + '">0</td>';
                
                tbody.appendChild(row);
            });
        }
        
        function updateTable() {
            symbols.forEach((symbol, idx) => {
                const data = digitData[symbol];
                const total = data.total || 1;
                
                for (let d = 0; d < 10; d++) {
                    const cell = document.getElementById('cell-' + idx + '-' + d);
                    const count = data.counts[d];
                    const freq = count / total;
                    
                    cell.textContent = count;
                    cell.className = 'digit-cell ';
                    if (freq > 0.15) cell.className += 'hot';
                    else if (freq < 0.05 && total > 20) cell.className += 'cold';
                    else cell.className += 'neutral';
                }
                
                document.getElementById('even-' + idx).textContent = data.even;
                document.getElementById('odd-' + idx).textContent = data.odd;
            });
        }
        
        function handleWSMessage(msg) {
            if (msg.type === 'tick') {
                const symbol = msg.data.symbol;
                const price = msg.data.quote;
                const lastDigit = parseInt(price.toString().slice(-1));
                
                if (digitData[symbol]) {
                    digitData[symbol].counts[lastDigit]++;
                    digitData[symbol].total++;
                    if (lastDigit % 2 === 0) digitData[symbol].even++;
                    else digitData[symbol].odd++;
                    
                    updateTable();
                }
            }
            if (msg.type === 'snapshot') {
                document.getElementById('balance').textContent = (msg.data.balance || 0).toFixed(2) + ' USD';
            }
        }
        
        function onAuthenticated(data) {
            document.getElementById('btn-login').textContent = '✓ Connected';
            document.getElementById('log-area').textContent = 'Connected! Receiving digit data...';
            initTable();
        }
        
        // Initialize table on load
        initTable();
    </script>
    '''
    
    return BASE_HTML.format(
        title="DigitPad - Deriv Trading",
        extra_styles=extra_styles,
        content=content,
        extra_scripts=extra_scripts
    )


# AMT Accumulator Page
@app.get("/amt", response_class=HTMLResponse)
async def amt_page():
    content = '''
        <div class="header">
            <div class="logo">LDP<span style="font-weight: normal; font-size: 1rem;">Accumulator</span></div>
            <div class="status">
                <div class="status-dot"></div>
                <span id="status-text">Offline</span>
            </div>
        </div>
        
        <div class="stats-grid" style="grid-template-columns: repeat(3, 1fr);">
            <div class="card" style="text-align: center;">
                <div class="card-title">Account</div>
                <div id="account">********</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">Balance</div>
                <div class="card-value blue" id="balance" style="font-size: 1.25rem;">0.00 USD</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">Profit</div>
                <div class="card-value green" id="profit" style="font-size: 1.25rem;">0.00 USD</div>
            </div>
        </div>
        
        <div class="card">
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <button class="btn btn-primary symbol-btn active" data-symbol="R_100">100v</button>
                <button class="btn btn-secondary symbol-btn" data-symbol="R_10">10v</button>
                <button class="btn btn-secondary symbol-btn" data-symbol="R_25">25v</button>
                <button class="btn btn-secondary symbol-btn" data-symbol="R_50">50v</button>
                <button class="btn btn-secondary symbol-btn" data-symbol="R_75">75v</button>
            </div>
        </div>
        
        <div class="chart-container" style="display: flex; align-items: center; justify-content: center;">
            <div style="text-align: center;">
                <div style="font-size: 4rem;">📊</div>
                <div style="color: var(--text-secondary);">Accumulator Growth Chart</div>
            </div>
        </div>
        
        <div class="card" style="margin-top: 16px;">
            <div id="console" style="font-family: monospace; font-size: 0.875rem; min-height: 100px; color: var(--text-secondary);">
                > Waiting for connection...
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="input-group">
                <label>Growth Rate</label>
                <select id="growth-rate">
                    <option value="1">1% (Safest)</option>
                    <option value="2">2%</option>
                    <option value="3" selected>3%</option>
                    <option value="4">4%</option>
                    <option value="5">5% (Riskiest)</option>
                </select>
            </div>
            <div class="input-group">
                <label>Stake ($)</label>
                <input type="number" id="stake" value="1" min="0.35">
            </div>
        </div>
        
        <div class="stats-grid">
            <div class="input-group">
                <label>Take Profit ($)</label>
                <input type="number" id="tp" value="10" min="0">
            </div>
            <div class="input-group">
                <label>Stop Loss ($)</label>
                <input type="number" id="sl" value="5" min="0">
            </div>
        </div>
        
        <button class="btn btn-primary" style="width: 100%; margin-top: 16px;" id="btn-start">
            ▶ START ACCUMULATOR
        </button>
    '''
    
    extra_scripts = '''
    <script>
        let selectedSymbol = 'R_100';
        let isRunning = false;
        
        document.querySelectorAll('.symbol-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.symbol-btn').forEach(b => {
                    b.classList.remove('btn-primary', 'active');
                    b.classList.add('btn-secondary');
                });
                btn.classList.remove('btn-secondary');
                btn.classList.add('btn-primary', 'active');
                selectedSymbol = btn.dataset.symbol;
                logConsole('Selected: ' + selectedSymbol, 'info');
            });
        });
        
        document.getElementById('btn-start').addEventListener('click', () => {
            isRunning = !isRunning;
            const btn = document.getElementById('btn-start');
            btn.textContent = isRunning ? '⏹ STOP ACCUMULATOR' : '▶ START ACCUMULATOR';
            btn.classList.toggle('btn-danger', isRunning);
            btn.classList.toggle('btn-primary', !isRunning);
            
            if (isRunning) {
                logConsole('Starting Accumulator on ' + selectedSymbol + '...', 'info');
            } else {
                logConsole('Accumulator stopped', 'info');
            }
        });
        
        function logConsole(msg, type = 'normal') {
            const c = document.getElementById('console');
            c.innerHTML += '<div style="color: ' + (type === 'error' ? 'var(--accent-red)' : type === 'info' ? 'var(--accent-blue)' : 'var(--text-secondary)') + '">> ' + new Date().toLocaleTimeString() + ' | ' + msg + '</div>';
            c.scrollTop = c.scrollHeight;
        }
        
        function handleWSMessage(msg) {
            if (msg.type === 'snapshot') {
                document.getElementById('balance').textContent = (msg.data.balance || 0).toFixed(2) + ' USD';
                updateConnectionStatus(true);
            }
        }
        
        function onAuthenticated(data) {
            logConsole('Authenticated as ' + (data.user.first_name || 'User'), 'info');
        }
    </script>
    '''
    
    return BASE_HTML.format(
        title="AMT Accumulator - Deriv Trading",
        extra_styles="",
        content=content,
        extra_scripts=extra_scripts
    )


# Sniper Page
@app.get("/sniper", response_class=HTMLResponse)
async def sniper_page():
    content = '''
        <div class="header">
            <div class="logo">LDP<span style="font-weight: normal; font-size: 1rem;">Sniper</span></div>
            <div style="display: flex; gap: 8px;">
                <button class="btn btn-primary" style="padding: 8px 16px;" id="btn-login">Login</button>
                <button class="btn btn-secondary" style="padding: 8px 16px;">🔄 Sniper Old</button>
            </div>
        </div>
        
        <div class="card" style="text-align: center; background: var(--bg-secondary);">
            <div style="font-size: 0.875rem; color: var(--text-secondary); margin-bottom: 8px;">SESSION STATISTICS</div>
        </div>
        
        <div class="stats-grid" style="grid-template-columns: repeat(3, 1fr);">
            <div class="card" style="text-align: center;">
                <div class="card-title">ACCOUNT</div>
                <div id="account">********</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">BALANCE</div>
                <div class="card-value" id="balance" style="font-size: 1.25rem;">00.00 USD</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">PROFIT</div>
                <div class="card-value green" id="profit" style="font-size: 1.25rem;">0.00 USD</div>
            </div>
        </div>
        
        <div class="stats-grid" style="grid-template-columns: repeat(3, 1fr);">
            <div class="card" style="text-align: center;">
                <div>WIN <span class="green" id="wins">0</span> | LOSE <span class="red" id="losses">0</span></div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">DURATION</div>
                <div id="duration">00:00:00</div>
            </div>
            <div class="card" style="text-align: center;">
                <div class="card-title">PING</div>
                <div id="ping">00 ms</div>
            </div>
        </div>
        
        <div class="stats-grid" style="grid-template-columns: 1fr 2fr;">
            <div class="card">
                <div style="text-align: center; margin-bottom: 16px; color: var(--text-secondary);">STRATEGY SELECTOR</div>
                
                <div style="background: var(--bg-secondary); border-radius: 8px; padding: 12px; margin-bottom: 8px; cursor: pointer;" onclick="selectStep(1)">
                    <span style="background: var(--accent-green); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">Step (1)</span>
                    <span style="margin-left: 8px;">💡 STRATEGY CHOOSER</span>
                </div>
                
                <div style="background: var(--bg-secondary); border-radius: 8px; padding: 12px; margin-bottom: 8px; cursor: pointer;" onclick="selectStep(2)">
                    <span style="background: var(--accent-blue); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">Step (2)</span>
                    <span style="margin-left: 8px;">🛡️ RISK MANAGEMENT</span>
                </div>
                
                <div style="background: var(--bg-secondary); border-radius: 8px; padding: 12px; margin-bottom: 8px; cursor: pointer;" onclick="selectStep(3)">
                    <span style="background: var(--accent-yellow); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">Step (3)</span>
                    <span style="margin-left: 8px;">💰 MONEY MANAGEMENT</span>
                </div>
                
                <div style="background: var(--bg-secondary); border-radius: 8px; padding: 12px; margin-bottom: 8px; cursor: pointer;" onclick="selectStep(4)">
                    <span style="margin-left: 8px;">⚙️ ADDITIONAL SETTING</span>
                </div>
                
                <div style="text-align: center; margin: 16px 0; color: var(--text-secondary);">TRADER ON/OFF</div>
                
                <button class="btn btn-primary" style="width: 100%;" id="btn-start">▶ START</button>
            </div>
            
            <div class="card">
                <div style="text-align: center; margin-bottom: 16px; color: var(--text-secondary);">TRADING OUTPUT CONSOLE</div>
                <div class="console" id="console" style="height: 300px;">
                    <div class="console-line info">> Please log in to your Deriv account & choose your strategy(Step 1) to start trading..</div>
                </div>
            </div>
        </div>
    '''
    
    extra_scripts = '''
    <script>
        let isTrading = false;
        let startTime = null;
        
        function selectStep(step) {
            logConsole('Selected Step ' + step, 'info');
        }
        
        document.getElementById('btn-start').addEventListener('click', () => {
            isTrading = !isTrading;
            const btn = document.getElementById('btn-start');
            btn.textContent = isTrading ? '⏹ STOP' : '▶ START';
            btn.style.background = isTrading ? 'var(--accent-red)' : 'var(--accent-green)';
            
            if (isTrading) {
                startTime = Date.now();
                logConsole('Sniper started - waiting for high probability signals...', 'info');
                updateDuration();
            } else {
                logConsole('Sniper stopped', 'info');
            }
        });
        
        function updateDuration() {
            if (!isTrading || !startTime) return;
            
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            const h = Math.floor(elapsed / 3600);
            const m = Math.floor((elapsed % 3600) / 60);
            const s = elapsed % 60;
            
            document.getElementById('duration').textContent = 
                h.toString().padStart(2, '0') + ':' + 
                m.toString().padStart(2, '0') + ':' + 
                s.toString().padStart(2, '0');
            
            setTimeout(updateDuration, 1000);
        }
        
        function logConsole(msg, type = 'normal') {
            const c = document.getElementById('console');
            const line = document.createElement('div');
            line.className = 'console-line ' + type;
            line.textContent = '> ' + new Date().toLocaleTimeString() + ' | ' + msg;
            c.appendChild(line);
            c.scrollTop = c.scrollHeight;
        }
        
        function handleWSMessage(msg) {
            if (msg.type === 'snapshot') {
                document.getElementById('balance').textContent = (msg.data.balance || 0).toFixed(2) + ' USD';
            }
            if (msg.type === 'signal' && isTrading) {
                if (msg.data.confidence >= 80) {
                    logConsole('SNIPER SIGNAL: ' + msg.data.direction + ' @ ' + msg.data.confidence + '%', 'info');
                }
            }
        }
        
        function onAuthenticated(data) {
            document.getElementById('btn-login').textContent = '✓ Connected';
            logConsole('Logged in as ' + (data.user.first_name || 'User'), 'info');
        }
    </script>
    '''
    
    return BASE_HTML.format(
        title="Sniper - Deriv Trading",
        extra_styles="",
        content=content,
        extra_scripts=extra_scripts
    )


# Strategy Router - Redirect based on selected strategy
@app.get("/app", response_class=HTMLResponse)
async def app_router(strategy: str = Query(None), token: str = Query(None)):
    """Route to appropriate WebApp based on selected strategy"""
    from fastapi.responses import RedirectResponse
    
    strategy_routes = {
        "TERMINAL": "/terminal",
        "TICK_PICKER": "/tick-picker",
        "DIGITPAD": "/digitpad",
        "AMT": "/amt",
        "ACCUMULATOR": "/amt",
        "SNIPER": "/sniper",
        "LDP": "/digitpad",
        "MULTI_INDICATOR": "/terminal",
        "TICK_ANALYZER": "/tick-picker"
    }
    
    if strategy and strategy.upper() in strategy_routes:
        target = strategy_routes[strategy.upper()]
        if token:
            target += f"?token={token}"
        return RedirectResponse(url=target)
    
    # Default to terminal
    return RedirectResponse(url="/terminal")


# ==================== API for Telegram Bot Integration ====================

@app.post("/api/telegram/set-strategy")
async def telegram_set_strategy(telegram_id: int = Query(...), strategy: str = Query(...)):
    """Set strategy from Telegram bot"""
    session_manager.set_strategy(telegram_id, strategy)
    
    user_id = str(telegram_id)
    if user_id in manager.active_connections:
        try:
            await manager.send_personal(user_id, {
                "type": "strategy_changed",
                "strategy": strategy
            })
        except:
            pass
    
    return {"success": True, "strategy": strategy}


@app.get("/api/telegram/get-webapp-url")
async def telegram_get_webapp_url(telegram_id: int = Query(...)):
    """Get WebApp URL with correct strategy"""
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
    
    route = strategy_routes.get(strategy, "/terminal") if strategy else "/terminal"
    
    return {
        "url": route,
        "strategy": strategy
    }


@app.get("/api/telegram/check-login")
async def check_telegram_login(telegram_id: int = Query(...)):
    """Check if Telegram user is logged in to Deriv via bot"""
    ws = deriv_connections.get(telegram_id)
    strategy = session_manager.get_strategy(telegram_id)
    
    if ws and ws.is_connected():
        return {
            "logged_in": True,
            "connected": True,
            "balance": ws.get_balance(),
            "currency": ws.get_currency(),
            "loginid": ws.loginid,
            "strategy": strategy,
            "account_type": "demo" if ws.loginid and "VRTC" in str(ws.loginid) else "real"
        }
    
    return {
        "logged_in": False,
        "connected": False,
        "strategy": strategy
    }


@app.get("/api/deriv/app-id")
async def get_deriv_app_id():
    """Get Deriv App ID for OAuth"""
    import os
    app_id = os.environ.get("DERIV_APP_ID", "1089")
    return {"app_id": app_id}


@app.post("/api/telegram/sync-deriv-token")
async def sync_deriv_token(telegram_id: int = Query(...), token: str = Query(...)):
    """Sync Deriv token from webapp to telegram bot session"""
    from deriv_ws import DerivWebSocket
    import os
    
    app_id = os.environ.get("DERIV_APP_ID", "1089")
    ws = DerivWebSocket(app_id=app_id)
    
    if not ws.connect():
        return {"success": False, "error": "Connection failed"}
    
    if not ws.authorize(token):
        ws.disconnect()
        return {"success": False, "error": "Invalid token"}
    
    deriv_connections[telegram_id] = ws
    
    return {
        "success": True,
        "balance": ws.get_balance(),
        "currency": ws.get_currency(),
        "loginid": ws.loginid
    }


# ==================== Startup ====================

def register_deriv_connection(telegram_id: int, ws):
    """Register Deriv WebSocket connection for a user"""
    deriv_connections[telegram_id] = ws


def register_strategy(name: str, strategy):
    """Register strategy instance"""
    strategy_instances[name] = strategy


async def broadcast_tick(symbol: str, tick_data: dict):
    """Broadcast tick to all connected WebSocket clients"""
    await manager.broadcast({
        "type": "tick",
        "data": {
            "symbol": symbol,
            **tick_data
        }
    })


async def broadcast_trade_result(user_id: str, result: dict):
    """Send trade result to specific user"""
    await manager.send_personal(user_id, {
        "type": "trade_result",
        "data": result
    })


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the web server"""
    uvicorn.run(app, host=host, port=port, log_level="info")


def run_server_thread(host: str = "0.0.0.0", port: int = 8000):
    """Run web server in a separate thread"""
    import threading
    thread = threading.Thread(target=run_server, args=(host, port), daemon=True)
    thread.start()
    logger.info(f"Web server started on http://{host}:{port}")
    return thread
