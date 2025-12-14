"""
Main Entry Point - Starts Telegram bot and web server
Complete integration of all components
"""

import os
import sys

# CRITICAL: Clear session files BEFORE importing any modules that use singletons
# This prevents loading stale session data into memory
def _early_cleanup():
    """Delete session files before module imports to prevent stale data loading"""
    log_files = [
        "logs/user_auth.json",
        "logs/session_recovery.json", 
        "logs/chat_mapping.json",
        "logs/.session_secret",
        "logs/trading_state.json"
    ]
    
    for file_path in log_files:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[STARTUP] Cleared: {file_path}")
        except:
            pass
    
    print("[STARTUP] Trading state cleared - fresh start")

# Run cleanup immediately before any other imports
_early_cleanup()

# Now safe to import modules - singletons will initialize with empty state
import logging
import asyncio
import signal
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Configure throttled logging for high-frequency modules
from logging_utils import configure_log_levels
configure_log_levels()

# Import components (singletons now load with no stale data)
from telegram_bot import TelegramBot
import web_server

# Global instances
bot: Optional[TelegramBot] = None
shutdown_event = asyncio.Event()


def clear_trading_managers():
    """Clear all trading managers from memory on startup/shutdown"""
    try:
        # Clear from web_server
        web_server.trading_managers.clear()
        web_server.deriv_connections.clear()
        web_server.session_manager.sessions.clear()
        web_server.session_manager.telegram_to_session.clear()
        web_server.session_manager.user_strategy.clear()
        web_server.session_manager.deriv_tokens.clear()
        web_server.session_manager.deriv_accounts.clear()
        logger.info("Cleared all trading managers and sessions from web_server")
    except Exception as e:
        logger.error(f"Failed to clear web_server state: {e}")
    
    try:
        # Clear from telegram_bot if it has trading managers
        from telegram_bot import TelegramBot
        # Note: TelegramBot instance's _trading_managers will be cleared when bot restarts
        logger.info("Telegram bot trading managers will be cleared on restart")
    except Exception as e:
        logger.error(f"Failed to import telegram_bot: {e}")


def clear_session_files():
    """Clear all session/log files on shutdown"""
    log_files = [
        "logs/user_auth.json",
        "logs/session_recovery.json", 
        "logs/chat_mapping.json",
        "logs/.session_secret",
        "logs/trading_state.json"
    ]
    
    for file_path in log_files:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleared session file: {file_path}")
        except Exception as e:
            logger.error(f"Failed to clear {file_path}: {e}")


async def main():
    """Main entry point"""
    global bot
    
    # Get environment variables - support multiple platforms
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    # Detect deployment platform and set URLs
    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    koyeb_domain = os.environ.get("KOYEB_PUBLIC_DOMAIN", "")
    app_url = os.environ.get("APP_URL", "")
    
    if replit_domain:
        webapp_base_url = f"https://{replit_domain}"
    elif koyeb_domain:
        webapp_base_url = f"https://{koyeb_domain}"
    elif app_url:
        webapp_base_url = app_url
    else:
        webapp_base_url = os.environ.get("WEBAPP_BASE_URL", "http://localhost:5000")
    
    # Koyeb uses PORT env var, fallback to WEB_PORT or 5000
    web_port = int(os.environ.get("PORT", os.environ.get("WEB_PORT", "5000")))
    
    if not telegram_token:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        logger.info("Please set TELEGRAM_BOT_TOKEN environment variable")
        logger.info("Get your token from @BotFather on Telegram")
        logger.info("For Koyeb deployment, set this in Environment Variables section")
        import time
        while True:
            logger.info("Waiting for TELEGRAM_BOT_TOKEN to be set...")
            time.sleep(60)
            telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            if telegram_token:
                logger.info("TELEGRAM_BOT_TOKEN detected, starting bot...")
                break
    
    # Create log directory
    os.makedirs("logs", exist_ok=True)
    
    logger.info("Session files cleared - fresh start")
    logger.info("=" * 60)
    logger.info("    DERIV AUTO TRADING BOT")
    logger.info("    With Multi-Strategy WebApps")
    logger.info("=" * 60)
    
    try:
        # Start web server in thread
        logger.info(f"Starting Web Server on port {web_port}...")
        web_server.start_server_thread(host="0.0.0.0", port=web_port)
        
        # Register webapp manager for trade event broadcasting
        from telegram_bot import set_webapp_manager
        set_webapp_manager(web_server.manager)
        
        # Small delay to ensure web server is ready
        await asyncio.sleep(1)
        
        # Start Telegram bot
        logger.info("Starting Telegram Bot...")
        bot = TelegramBot(telegram_token, webapp_base_url=webapp_base_url)
        await bot.start()
        
        # Clear all trading managers from memory after bot start
        clear_trading_managers()
        logger.info("Trading state cleared from memory - ready for fresh trading")
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("   BOT STARTED SUCCESSFULLY!")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Available WebApps:")
        logger.info(f"  - Terminal:    {webapp_base_url}/terminal")
        logger.info(f"  - Tick Picker: {webapp_base_url}/tick-picker")
        logger.info(f"  - DigitPad:    {webapp_base_url}/digitpad")
        logger.info(f"  - AMT:         {webapp_base_url}/amt")
        logger.info(f"  - Sniper:      {webapp_base_url}/sniper")
        logger.info("")
        logger.info("Telegram Bot Commands:")
        logger.info("  /start    - Start the bot")
        logger.info("  /login    - Login to Deriv")
        logger.info("  /strategi - Choose strategy")
        logger.info("  /webapp   - Open WebApp")
        logger.info("  /help     - Show help")
        logger.info("")
        
        # Wait for shutdown signal
        await shutdown_event.wait()
        
    except Exception as e:
        logger.error(f"Error in main: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        # Cleanup
        if bot:
            await bot.stop()
        
        # Clear session files on shutdown
        clear_session_files()
        logger.info("Shutdown complete - all sessions cleared")


def handle_shutdown(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    shutdown_event.set()


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    # Print startup banner
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║          DERIV AUTO TRADING BOT v2.0                      ║
    ║          Multi-Strategy WebApp Integration                ║
    ║                                                           ║
    ║   Strategies:                                             ║
    ║   - Terminal (Smart Analysis 80%)                         ║
    ║   - Tick Picker (Pattern Analysis)                        ║
    ║   - DigitPad (Digit Frequency)                            ║
    ║   - AMT Accumulator (Growth Rate)                         ║
    ║   - Sniper (High Probability 80%+)                        ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
