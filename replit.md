# Deriv Auto Trading Bot

## Overview
This project is a Python-based Telegram bot designed for automated trading on the Deriv platform. It integrates with Deriv via WebSocket API, offers five distinct trading strategies, and features a Telegram WebApp for user interaction and configuration. The primary purpose is to provide users with a robust, secure, and user-friendly tool for executing automated trading strategies, aiming for high win rates and efficient risk management.

## User Preferences
I want to work iteratively.
I prefer to get a detailed explanation for each change.
I want to be asked before you make any major changes to the codebase.
Do not make changes to the `webapps/` folder, it contains static assets.
Do not make changes to the file `deriv_ws.py`, it is a core dependency.

## System Architecture
The system is built around a FastAPI backend (`web_server.py`) serving both API endpoints and static HTML/JavaScript WebApp interfaces for each trading strategy. A separate Python module (`telegram_bot.py`) handles Telegram bot interactions, including inline keyboards and WebApp integration. Communication with the Deriv trading platform is managed via a dedicated WebSocket client (`deriv_ws.py`).

**Key Architectural Decisions:**
- **Python-centric Implementation:** The entire application, including the UI, is implemented in Python with FastAPI for the backend, simplifying development and deployment.
- **Microservices-like Structure:** Core functionalities like Deriv WebSocket communication, Telegram bot logic, and trading managers are encapsulated in separate modules.
- **Session-based Authentication:** Secure, session-based authentication is implemented for Telegram WebApp users, leveraging `initData` for validation.
- **Risk Management Integration:** Advanced risk management features such as Fibonacci-based recovery, auto-pause on consecutive losses, dynamic session limits, and entry filtering are integral to the trading managers.
- **Deployment:** Optimized for deployment on platforms like Koyeb Free Tier with built-in keep-alive mechanisms.

**UI/UX Decisions:**
- Each trading strategy has its own dedicated HTML/JavaScript WebApp interface for configuration and monitoring.
- The main Telegram bot uses inline keyboards for initial interaction and launching WebApps.

**Feature Specifications:**
- **5 Trading Strategies:** Terminal, Tick Picker, DigitPad, AMT (Accumulator), Sniper.
- **Telegram WebApp Integration:** Seamless user experience for configuring strategies and managing trades directly within Telegram.
- **Real-time Performance Monitoring:** Via an API endpoint for metrics.
- **Persistent User Settings:** Storage for user preferences and strategy configurations.
- **Robust Error Handling:** Includes retry mechanisms for authorization and connection stability.

**System Design Choices:**
- **FastAPI:** Chosen for its high performance, ease of use, and asynchronous capabilities.
- **WebSocket Communication:** Utilized for real-time data exchange with Deriv and between the WebApp and backend.
- **Modular Design:** Encourages maintainability and scalability by separating concerns into distinct Python modules.

## Enhanced Professional Modules (December 2025)

### 1. Backtesting Engine (`backtesting.py`)
- Historical data testing with walk-forward optimization
- Monte Carlo simulation for robustness testing
- Comprehensive metrics: Sharpe ratio, Sortino ratio, profit factor, drawdown
- Strategy optimizer with grid search
- Classes: `BacktestEngine`, `HistoricalDataLoader`, `StrategyOptimizer`, `BacktestResult`

### 2. Notification Manager (`notification_manager.py`)
- Real-time trade notifications with rate limiting
- Daily and weekly summary reports
- Profit milestone alerts and drawdown warnings
- Win/loss streak notifications
- Class: `NotificationManager` (singleton: `notification_manager`)

### 3. Portfolio Manager (`portfolio_manager.py`)
- Real-time equity curve tracking
- Position management and trade recording
- Risk metrics: Sharpe, Sortino, Calmar, VaR
- Symbol and strategy performance breakdown
- Classes: `PortfolioManager`, `PortfolioManagerFactory`

### 4. Circuit Breaker (`circuit_breaker.py`)
- Circuit breaker pattern (OPEN, CLOSED, HALF_OPEN states)
- Token bucket rate limiter
- Retry with exponential backoff and jitter
- API client wrapper for robust communication
- Classes: `CircuitBreaker`, `RateLimiter`, `RetryWithBackoff`, `APIClient`

### 5. Signal Aggregator (`signal_aggregator.py`)
- Weighted voting aggregation
- Consensus and unanimous methods
- Best performer selection
- Meta-learning with adaptive weights based on performance
- Class: `SignalAggregator` (singleton: `signal_aggregator`)

### 6. Session Awareness (`session_awareness.py`)
- Market session detection: Asian, European, American, Pacific
- Session quality scoring and overlap detection
- Strategy recommendations per session
- Class: `TradingSessionManager` (singleton: `session_manager`)

### 7. Enhanced Logging (`enhanced_logging.py`)
- Structured JSON logging with log rotation
- In-memory buffer for real-time log viewing
- Throttled handler for repeated messages
- Colored console output
- Functions: `setup_logging()`, `get_recent_logs()`, `get_error_logs()`

### 8. User Authentication (`user_auth.py`)
- Per-user encrypted token storage (Fernet/AES-128-CBC)
- PBKDF2 key derivation (100,000 iterations)
- Rate limiting for login attempts
- Token rotation support (24-hour interval)
- Session timeout management (7-day inactivity)
- Session statistics and cleanup
- Class: `UserAuth` (singleton: `user_auth`)

## External Dependencies
- **Deriv API:** Core trading functionality, accessed via WebSocket.
- **Telegram Bot API:** For bot interactions and WebApp integration.
- **FastAPI:** Python web framework for the backend.
- **Uvicorn:** ASGI server to run the FastAPI application.
- **Koyeb:** (Optional) Deployment platform, with specific configurations for 24/7 free tier operation.
- **cryptography:** For secure token encryption.

## Recent Changes
- **December 15, 2025 (Latest):** 
  - Achieved ZERO LSP errors across entire codebase
  - Fixed telegram_bot.py: 5 null safety issues (self.application.bot checks)
  - Fixed unlimited mode display bug: Now correctly shows "∞" for target_trades when unlimited
  - Watchdog stuck detection working properly with progressive recovery (30s health check, 45s pending clear, 60s auto-restart)
- **December 15, 2025:** Added 8 professional enhancement modules for backtesting, notifications, portfolio management, circuit breaker, signal aggregation, session awareness, enhanced logging, and security hardening.
