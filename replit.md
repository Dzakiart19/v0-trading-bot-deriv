# Deriv Auto Trading Bot

## Overview
A Python-based Telegram bot for Deriv trading with 5 strategies and WebApp integration.

## Current State
- Full Python implementation (migrated from Next.js)
- FastAPI backend on port 5000
- Telegram Bot with inline keyboards and WebApp support
- 5 trading strategies with individual WebApps

## Strategies
1. **Terminal** - Smart analysis with 80% win rate target
2. **Tick Picker** - Pattern analysis for digit prediction
3. **DigitPad** - Digit frequency analysis
4. **AMT** - Accumulator strategy with growth rate
5. **Sniper** - High probability trades (80%+)

## Architecture
- `main.py` - Entry point, starts both Telegram bot and web server
- `telegram_bot.py` - Telegram bot with commands and WebApp integration
- `web_server.py` - FastAPI server with WebSocket and strategy pages
- `deriv_ws.py` - Deriv WebSocket API client
- `*_strategy.py` - Individual strategy implementations

## Environment Variables Required
- `TELEGRAM_BOT_TOKEN` - Get from @BotFather on Telegram
- `DERIV_API_TOKEN` (optional) - Deriv API token for trading

## Recent Changes
- 2024-12: Migrated from Next.js to full Python
- Removed all Node.js dependencies
- Configured for Replit environment with port 5000
