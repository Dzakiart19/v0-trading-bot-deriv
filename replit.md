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
- 2024-12-09: Fixed security issues in sync endpoints - now require valid session token
- 2024-12-09: Added sessionValidated flag for secure Telegram authentication
- 2024-12-09: Cleaned web_server.py - removed duplicate routes, serve HTML from webapps/
- 2024-12: Migrated from Next.js to full Python
- Configured for Replit environment with port 5000
