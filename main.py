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
        "logs/.session_secret"
    ]
    
    for file_path in log_files:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except:
            pass

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

# Import components (singletons now load with no stale data)
from telegram_bot import TelegramBot
import web_server

# Global instances
bot: Optional[TelegramBot] = None
shutdown_event = asyncio.Event()


def clear_session_files():
    """Clear all session/log files on shutdown"""
    log_files = [
        "logs/user_auth.json",
        "logs/session_recovery.json", 
        "logs/chat_mapping.json",
        "logs/.session_secret"
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
    
    # Get environment variables
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
    webapp_base_url = f"https://{replit_domain}" if replit_domain else os.environ.get("WEBAPP_BASE_URL", "http://localhost:5000")
    web_port = int(os.environ.get("WEB_PORT", "5000"))
    
    if not telegram_token:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        logger.info("Please set TELEGRAM_BOT_TOKEN environment variable")
        logger.info("Get your token from @BotFather on Telegram")
        return
    
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
        
        # Small delay to ensure web server is ready
        await asyncio.sleep(1)
        
        # Start Telegram bot
        logger.info("Starting Telegram Bot...")
        bot = TelegramBot(telegram_token, webapp_base_url=webapp_base_url)
        await bot.start()
        
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
