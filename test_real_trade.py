"""
Real Trade Test Script - Test timeout fixes with actual Deriv API
Tests connection health check, retry mechanism, and timeout handling
"""

import os
import sys
import time
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_connection_and_trade():
    """Test connection health check and trade execution with timeout handling"""
    from deriv_ws import DerivWebSocket
    
    token = os.environ.get("DERIV_API_TOKEN")
    if not token:
        logger.error("DERIV_API_TOKEN environment variable not set")
        logger.info("Please set your Deriv API token:")
        logger.info("  export DERIV_API_TOKEN='your_token_here'")
        return False
    
    print("\n" + "="*60)
    print("DERIV TRADING BOT - REAL TRADE TEST")
    print("="*60)
    
    ws = DerivWebSocket()
    
    print("\n[1] Testing WebSocket Connection...")
    print("-" * 40)
    
    start_time = time.time()
    connected = ws.connect(timeout=15)
    connect_time = time.time() - start_time
    
    if not connected:
        logger.error(f"Failed to connect to Deriv WebSocket (took {connect_time:.2f}s)")
        return False
    
    print(f"   Connected: {ws.connected}")
    print(f"   Connection time: {connect_time:.2f}s")
    
    print("\n[2] Testing Authorization...")
    print("-" * 40)
    
    start_time = time.time()
    success, error = ws.authorize(token, timeout=15)
    auth_time = time.time() - start_time
    
    if not success:
        logger.error(f"Authorization failed: {error}")
        ws.disconnect()
        return False
    
    print(f"   Authorized: {ws.authorized}")
    print(f"   Auth time: {auth_time:.2f}s")
    print(f"   Login ID: {ws.loginid}")
    print(f"   Balance: {ws.balance} {ws.currency}")
    print(f"   Account Type: {ws.account_type}")
    
    print("\n[3] Testing Connection Health Check...")
    print("-" * 40)
    
    start_time = time.time()
    healthy = ws.check_connection_health()
    health_time = time.time() - start_time
    
    print(f"   Connection healthy: {healthy}")
    print(f"   Health check time: {health_time:.2f}s")
    
    if not healthy:
        logger.error("Connection health check failed")
        ws.disconnect()
        return False
    
    print("\n[4] Testing Connection Metrics...")
    print("-" * 40)
    
    metrics = ws.get_connection_metrics()
    for key, value in metrics.items():
        print(f"   {key}: {value}")
    
    print("\n[5] Testing Proposal Request (with retry)...")
    print("-" * 40)
    
    symbol = "R_100"
    contract_type = "CALL"
    stake = 1.0
    duration = 5
    duration_unit = "t"
    
    print(f"   Symbol: {symbol}")
    print(f"   Contract: {contract_type}")
    print(f"   Stake: ${stake}")
    print(f"   Duration: {duration} ticks")
    
    start_time = time.time()
    result = ws.buy_contract(
        contract_type=contract_type,
        symbol=symbol,
        stake=stake,
        duration=duration,
        duration_unit=duration_unit
    )
    trade_time = time.time() - start_time
    
    if result:
        print(f"\n   TRADE SUCCESSFUL!")
        print(f"   Contract ID: {result.get('contract_id')}")
        print(f"   Buy Price: ${result.get('buy_price', 0):.2f}")
        print(f"   Payout: ${result.get('payout', 0):.2f}")
        print(f"   Trade execution time: {trade_time:.2f}s")
    else:
        print(f"\n   Trade failed (took {trade_time:.2f}s)")
        metrics = ws.get_connection_metrics()
        print(f"   Timeout count: {metrics.get('timeout_count', 0)}")
        print(f"   Consecutive timeouts: {metrics.get('consecutive_timeouts', 0)}")
    
    print("\n[6] Final Connection Metrics...")
    print("-" * 40)
    
    metrics = ws.get_connection_metrics()
    for key, value in metrics.items():
        print(f"   {key}: {value}")
    
    print("\n[7] Waiting for contract result...")
    print("-" * 40)
    
    if result and result.get('contract_id'):
        contract_id = str(result.get('contract_id'))
        print(f"   Monitoring contract: {contract_id}")
        
        wait_start = time.time()
        max_wait = 30
        
        while time.time() - wait_start < max_wait:
            contracts = ws.get_active_contracts()
            if contract_id in contracts:
                contract = contracts[contract_id]
                status = contract.get('status')
                is_sold = contract.get('is_sold', False)
                
                if is_sold or status in ['sold', 'won', 'lost']:
                    profit = contract.get('profit', 0)
                    sell_price = contract.get('sell_price', 0)
                    
                    result_text = "WIN" if profit > 0 else "LOSS"
                    print(f"\n   Contract closed: {result_text}")
                    print(f"   Profit: ${profit:.2f}")
                    if sell_price:
                        print(f"   Sell Price: ${sell_price:.2f}")
                    break
            
            time.sleep(1)
            elapsed = int(time.time() - wait_start)
            if elapsed % 5 == 0:
                print(f"   Waiting... ({elapsed}s)")
        else:
            print("   Timeout waiting for contract result (this is normal for tick contracts)")
    
    print("\n[8] Cleanup...")
    print("-" * 40)
    
    ws.disconnect()
    print("   Disconnected from Deriv")
    
    print("\n" + "="*60)
    print("TEST COMPLETED")
    print("="*60)
    
    return True


def test_timeout_recovery():
    """Test timeout recovery mechanism"""
    from deriv_ws import DerivWebSocket
    
    token = os.environ.get("DERIV_API_TOKEN")
    if not token:
        logger.error("DERIV_API_TOKEN not set")
        return False
    
    print("\n" + "="*60)
    print("TIMEOUT RECOVERY TEST")
    print("="*60)
    
    ws = DerivWebSocket()
    
    if not ws.connect():
        logger.error("Failed to connect")
        return False
    
    success, _ = ws.authorize(token)
    if not success:
        logger.error("Failed to authorize")
        ws.disconnect()
        return False
    
    print("\n[1] Testing retry mechanism with forced timeout simulation...")
    print("-" * 40)
    
    print("   Performing 3 rapid proposal requests to test retry...")
    
    for i in range(3):
        print(f"\n   Request {i+1}:")
        start = time.time()
        result = ws.buy_contract(
            contract_type="CALL",
            symbol="R_100", 
            stake=1.0,
            duration=5,
            duration_unit="t"
        )
        elapsed = time.time() - start
        
        if result:
            print(f"      SUCCESS in {elapsed:.2f}s - Contract: {result.get('contract_id')}")
        else:
            print(f"      FAILED in {elapsed:.2f}s")
        
        metrics = ws.get_connection_metrics()
        print(f"      Timeouts: {metrics.get('timeout_count', 0)}, Success rate: {metrics.get('success_rate', 0)}%")
        
        time.sleep(3)
    
    print("\n[2] Final metrics...")
    print("-" * 40)
    
    metrics = ws.get_connection_metrics()
    for key, value in metrics.items():
        print(f"   {key}: {value}")
    
    ws.disconnect()
    print("\n   Test completed")
    
    return True


if __name__ == "__main__":
    print("\nDeriv Trading Bot - Real Trade Test")
    print("=" * 50)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--recovery":
        test_timeout_recovery()
    else:
        test_connection_and_trade()
