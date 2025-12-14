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

## External Dependencies
- **Deriv API:** Core trading functionality, accessed via WebSocket.
- **Telegram Bot API:** For bot interactions and WebApp integration.
- **FastAPI:** Python web framework for the backend.
- **Uvicorn:** ASGI server to run the FastAPI application.
- **Koyeb:** (Optional) Deployment platform, with specific configurations for 24/7 free tier operation.