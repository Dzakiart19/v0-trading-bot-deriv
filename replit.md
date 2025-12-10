# Deriv Auto Trading Bot

## Overview
A Python-based Telegram bot for Deriv trading with 5 strategies and WebApp integration.

## Current State
- Full Python implementation (migrated from Next.js)
- FastAPI backend on port 5000
- Telegram Bot with inline keyboards and WebApp support
- 5 trading strategies with individual WebApps
- Secure session-based authentication for Telegram WebApp

## Strategies
1. **Terminal** - Smart analysis with 80% win rate target
2. **Tick Picker** - Pattern analysis for digit prediction
3. **DigitPad** - Digit frequency analysis
4. **AMT** - Accumulator strategy with growth rate
5. **Sniper** - High probability trades (80%+)

## Architecture
- `web_server.py` - FastAPI server with WebSocket, API endpoints, and strategy pages
- `deriv_ws.py` - Deriv WebSocket API client
- `webapps/` - HTML strategy web interfaces
  - `index.html` - Main landing page with strategy selection
  - `terminal.html` - Terminal strategy UI
  - `tick-picker.html` - Tick Picker strategy UI
  - `digitpad.html` - DigitPad strategy UI
  - `amt.html` - AMT Accumulator strategy UI
  - `sniper.html` - Sniper strategy UI

## API Endpoints
- `GET /` - Main index page
- `GET /{strategy}` - Individual strategy pages
- `POST /api/auth/telegram` - Telegram WebApp authentication
- `GET /api/telegram/check-login` - Check if user logged in via Telegram
- `POST /api/telegram/sync-deriv-token` - Sync Deriv token (requires session)
- `POST /api/telegram/sync-deriv-account` - Sync Deriv account (requires session)
- `GET /api/strategy/configs` - Get all strategy configurations (stakes, trade counts)
- `GET /api/strategy/{name}/config` - Get single strategy configuration
- `GET /api/user/strategy` - Get selected strategy
- `POST /api/user/strategy` - Set selected strategy
- `POST /api/trade/place` - Place a trade
- `POST /api/auto-trade/start` - Start auto trading
- `POST /api/auto-trade/stop` - Stop auto trading

## Security Features
- Session-based authentication via Telegram WebApp initData
- Session token validation on all sync endpoints
- `sessionValidated` flag prevents replay attacks
- No unauthenticated writes to user Deriv tokens

## Environment Variables Required
- `TELEGRAM_BOT_TOKEN` - Get from @BotFather on Telegram
- `DERIV_APP_ID` (optional) - Deriv OAuth App ID (default: 1089)
- `DERIV_API_TOKEN` (optional) - Deriv API token for trading

## Recent Changes
- 2025-12-10: **FIX - Entry Price = 0 Bug** - Added fallback chain for entry_price: entry_spot → entry_tick_price → buy_price to ensure analytics always have valid entry price
- 2025-12-10: **Enhanced Logging** - Added comprehensive emoji-based logging throughout trade flow (_on_tick, _process_signal, _execute_trade_worker) for easier debugging
- 2025-12-10: **Error Handling** - Added try-except wrappers in signal processing to catch and log errors without crashing the bot
- 2025-12-10: **MAJOR FIX - Fibonacci Recovery** - Replaced aggressive 2x Martingale with Fibonacci sequence (1,1,2,3,5,8,13,21) for stake recovery
- 2025-12-10: **Trade History Analyzer** - Added pattern detection and auto-pause after 3+ consecutive losses
- 2025-12-10: **Performance Monitor** - Real-time metrics tracking with /api/metrics endpoint
- 2025-12-10: **User Preferences** - Persistent settings storage in config/users/
- 2025-12-10: **Dynamic Session Limits** - Strategy-specific loss limits (AMT=30%, SNIPER=15%, DIGITPAD=25%)
- 2025-12-10: **Entry Filtering** - Strategy-specific confidence thresholds (AMT=75%, SNIPER=80%)
- 2025-12-10: **Max Stake Cap** - Reduced from 20% to 10% of balance for safer trading
- 2025-12-10: **Strategy Configurations** - Added `strategy_config.py` with stake options and trade count options for all 8 strategies
- 2025-12-10: **API Endpoint** - Added `/api/strategy/configs` and `/api/strategy/{name}/config` endpoints
- 2025-12-10: **AMT Trade Count UI** - Added trade count selection (5, 10, 20, 50, 100, Unlimited) to AMT webapp
- 2025-12-10: **Auto Trade Test** - Created `auto_trade_test.py` for testing real trades with token 074qAV4XaEqz8Jl
- 2025-12-10: **All 8 Strategies Working** - Verified all strategies trade correctly via test_strategy_trades.py
- 2025-12-10: **AMT Accumulator Fix** - Enforced $1.00 minimum stake requirement (Deriv API limitation)
- 2025-12-10: **Removed limit_order** - Accumulator contracts no longer use limit_order field (was causing timeouts)
- 2025-12-09: **AMT Accumulator Fix** - Changed growth rate to conservative 1-2% (was 3-5%) for wider barriers and less barrier hits
- 2025-12-09: **AMT Accumulator Fix** - Changed take_profit from 200% to 50% of stake for faster/more consistent wins
- 2025-12-09: **CRITICAL FIX** - WebSocket reconnect with auto re-authorization dan state recovery
- 2025-12-09: Timeout proposal/buy dinaikkan dari 10s ke 20s untuk stabilitas
- 2025-12-09: Ping interval dikurangi dari 60s ke 30s (sesuai Deriv best practices)
- 2025-12-09: Menambahkan _on_connection_status callback di TradingManager untuk auto-resume setelah reconnect
- 2025-12-09: Menambahkan re-subscribe tick otomatis setelah reconnect
- 2025-12-09: Dibuat test_all_strategies.py untuk testing komprehensif semua strategi
- 2025-12-09: **Critical Fix** - Trading timeout mitigation with retry mechanism and exponential backoff
- 2025-12-09: Added connection health check (check_connection_health, get_connection_metrics) for debugging
- 2025-12-09: Enhanced _send_and_wait with retry support (configurable retries, timeout tracking)
- 2025-12-09: Added watchdog timer in TradingManager for stuck detection (20s check, 120s threshold)
- 2025-12-09: Added /api/debug endpoint for real-time connection and trading state monitoring
- 2025-12-09: Created test_real_trade.py script for verifying timeout fixes
- 2025-12-09: **Critical Fix** - Session files now cleared BEFORE module imports to prevent stale data
- 2025-12-09: Added `_early_cleanup()` in main.py that runs before any singleton imports
- 2025-12-09: Added `reset_all()` methods to user_auth.py and chat_mapping.py for in-memory purge
- 2025-12-09: Enhanced trading callbacks with proper async event loop capture for Telegram notifications
- 2025-12-09: Added Indonesian language trade notifications (`_notify_trade_opened`, `_notify_trade_closed`)
- 2025-12-09: Fixed WebApp auto-connect issue - now syncs Deriv token and account info to session_manager when login via Telegram bot
- 2025-12-09: Added `clear_user_data()` helper to WebSessionManager for centralized cleanup on logout
- 2025-12-09: Logout handlers now properly clear session_manager data to prevent stale sessions
- 2024-12-09: Fixed security issues in sync endpoints - now require valid session token
- 2024-12-09: Added sessionValidated flag for secure Telegram authentication
- 2024-12-09: Cleaned web_server.py - removed duplicate routes, serve HTML from webapps/
- 2024-12: Migrated from Next.js to full Python
- Configured for Replit environment with port 5000

## Session Management
- Session files (`logs/user_auth.json`, `logs/chat_mapping.json`, etc.) are deleted on EVERY bot startup
- This ensures fresh start with no stale sessions from previous runs
- Files are also deleted on shutdown for security
- Cleanup runs BEFORE module imports to prevent singleton pre-loading stale data

## Key Risk Management Features
1. **Fibonacci-Based Recovery** - Stake recovery using sequence: 1, 1, 2, 3, 5, 8, 13, 21 (max 8 levels)
2. **Auto-Pause** - Trading pauses after 3+ consecutive losses
3. **Loss Warnings** - Notifications at 50%, 75%, 90% of session loss limit
4. **Dynamic Limits** - Strategy-specific session loss limits (10-30% of balance)
5. **Entry Filtering** - Minimum confidence thresholds per strategy
6. **Max Stake Cap** - Never exceeds 10% of balance per trade

## New Files Added
- `hybrid_money_manager.py` - Fibonacci-based stake recovery system
- `trade_analyzer.py` - Trade history analysis and pattern detection
- `performance_monitor.py` - Real-time performance metrics
- `user_preferences.py` - Persistent user settings storage
- `entry_filter.py` - Signal filtering with strategy-specific thresholds
