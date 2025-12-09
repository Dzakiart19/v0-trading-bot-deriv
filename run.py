#!/usr/bin/env python3
"""
Quick start script for Deriv Auto Trading Bot
"""

import os
import sys

def main():
    # Load environment variables from .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("python-dotenv not installed. Using system environment variables.")
    
    # Check required environment variables
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_telegram_bot_token_here":
        print("""
=========================================
  DERIV AUTO TRADING BOT - SETUP
=========================================

ERROR: TELEGRAM_BOT_TOKEN is not configured!

To set up:
1. Create a bot via @BotFather on Telegram
2. Copy the token you receive
3. Edit .env file and paste your token:
   
   TELEGRAM_BOT_TOKEN=your_actual_token_here

4. Run this script again

=========================================
        """)
        sys.exit(1)
    
    # Import and run main
    try:
        from main import main as run_bot
        import asyncio
        asyncio.run(run_bot())
    except ImportError as e:
        print(f"Import error: {e}")
        print("\nMake sure all dependencies are installed:")
        print("  pip install -r requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
