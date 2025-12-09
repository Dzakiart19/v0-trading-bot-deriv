#!/usr/bin/env python3
"""
Test Deriv WebSocket connection
"""

import os
import sys
import time

def main():
    print("=" * 50)
    print("  DERIV CONNECTION TEST")
    print("=" * 50)
    print()
    
    # Load env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except:
        pass
    
    # Import DerivWebSocket
    try:
        from deriv_ws import DerivWebSocket
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure you run this from the scripts directory")
        sys.exit(1)
    
    app_id = os.environ.get("DERIV_APP_ID", "") or "1089"
    
    print(f"App ID: {app_id}")
    print("Connecting to Deriv...")
    print()
    
    ws = DerivWebSocket(app_id=app_id)
    
    if ws.connect():
        print("Connected successfully!")
        print()
        
        # Test authorization if token provided
        test_token = input("Enter Deriv API token (or press Enter to skip): ").strip()
        
        if test_token:
            print()
            print("Authorizing...")
            
            if ws.authorize(test_token):
                print()
                print("Authorization successful!")
                print(f"  Login ID: {ws.loginid}")
                print(f"  Balance: {ws.balance:.2f} {ws.currency}")
                print()
                
                # Subscribe to test ticks
                print("Subscribing to R_100 ticks...")
                
                tick_count = 0
                def on_tick(tick):
                    nonlocal tick_count
                    tick_count += 1
                    print(f"  Tick {tick_count}: {tick['quote']}")
                
                if ws.subscribe_ticks("R_100", on_tick):
                    print("Receiving ticks (5 seconds)...")
                    time.sleep(5)
                    ws.unsubscribe_ticks("R_100")
                    print()
                    print(f"Received {tick_count} ticks")
                else:
                    print("Failed to subscribe")
            else:
                print("Authorization failed!")
                print("Check your API token")
        
        ws.disconnect()
        print()
        print("Test completed!")
    else:
        print("Connection failed!")
        print("Check your internet connection")
        sys.exit(1)

if __name__ == "__main__":
    main()
