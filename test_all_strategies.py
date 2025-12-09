#!/usr/bin/env python3
"""
Test All Strategies - Script untuk menguji semua strategi trading dengan akun demo
Tujuan: Memastikan setiap strategi berjalan lancar tanpa stuck atau timeout

Strategi yang diuji:
1. MULTI_INDICATOR - Strategi multi-indikator (RSI, EMA, MACD, dll)
2. LDP - Last Digit Prediction
3. TICK_ANALYZER - Analisis tick untuk prediksi
4. TERMINAL - Terminal trading strategy
5. TICK_PICKER - Tick picker untuk digit trading
6. DIGITPAD - Digit pad strategy
7. AMT - Accumulator strategy
8. SNIPER - High confidence sniper strategy

Penggunaan:
    python test_all_strategies.py [--token TOKEN] [--strategy STRATEGY] [--trades N]
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, Optional, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Test configuration
TEST_CONFIG = {
    "symbol": "R_100",  # Volatility 100 Index (paling stabil untuk testing)
    "base_stake": 0.35,  # Stake minimum
    "duration": 5,
    "duration_unit": "t",
    "max_trades": 3,  # 3 trades per strategi untuk test cepat
    "timeout_per_trade": 60,  # Max 60 detik per trade
}


class StrategyTester:
    """Tester untuk semua strategi trading"""
    
    def __init__(self, token: str, verbose: bool = True):
        self.token = token
        self.verbose = verbose
        self.results: Dict[str, Dict[str, Any]] = {}
        self.ws = None
        
    def log(self, msg: str, level: str = "info"):
        """Log dengan level"""
        if self.verbose:
            if level == "error":
                logger.error(msg)
            elif level == "warning":
                logger.warning(msg)
            elif level == "success":
                logger.info(f"✅ {msg}")
            else:
                logger.info(msg)
    
    def connect(self) -> bool:
        """Koneksi ke Deriv API"""
        from deriv_ws import DerivWebSocket
        
        self.log("Menghubungkan ke Deriv API...")
        self.ws = DerivWebSocket()
        
        if not self.ws.connect(timeout=15):
            self.log("Gagal terhubung ke Deriv API", "error")
            return False
        
        self.log("Terhubung ke Deriv API", "success")
        
        # Authorize
        self.log(f"Mengotorisasi dengan token...")
        success, error = self.ws.authorize(self.token, timeout=15)
        
        if not success:
            self.log(f"Gagal otorisasi: {error}", "error")
            return False
        
        self.log(f"Otorisasi berhasil! Akun: {self.ws.loginid}, Saldo: {self.ws.balance} {self.ws.currency}", "success")
        return True
    
    def disconnect(self):
        """Putuskan koneksi"""
        if self.ws:
            self.ws.disconnect()
            self.log("Terputus dari Deriv API")
    
    def test_connection_health(self) -> bool:
        """Test koneksi kesehatan"""
        self.log("\n" + "="*60)
        self.log("TEST KESEHATAN KONEKSI")
        self.log("="*60)
        
        if not self.ws:
            return False
        
        # Test ping
        self.log("Mengirim ping...")
        start = time.time()
        is_healthy = self.ws.check_connection_health()
        elapsed = time.time() - start
        
        if is_healthy:
            self.log(f"Ping sukses dalam {elapsed:.2f}s", "success")
        else:
            self.log(f"Ping gagal setelah {elapsed:.2f}s", "error")
            return False
        
        # Test metrics
        metrics = self.ws.get_connection_metrics()
        self.log(f"Metrik koneksi:")
        self.log(f"  - Connected: {metrics.get('connected')}")
        self.log(f"  - Authorized: {metrics.get('authorized')}")
        self.log(f"  - Success Rate: {metrics.get('success_rate')}%")
        self.log(f"  - Timeout Count: {metrics.get('timeout_count')}")
        
        return True
    
    def test_tick_subscription(self, symbol: str = "R_100") -> bool:
        """Test subscription tick"""
        self.log("\n" + "="*60)
        self.log(f"TEST SUBSCRIPTION TICK ({symbol})")
        self.log("="*60)
        
        if not self.ws:
            return False
        
        tick_count = 0
        tick_received = []
        
        def on_tick(tick):
            nonlocal tick_count
            tick_count += 1
            tick_received.append(tick)
            if tick_count <= 3:
                self.log(f"  Tick {tick_count}: {tick.get('quote')}")
        
        # Subscribe
        self.log(f"Subscribing ke {symbol}...")
        if not self.ws.subscribe_ticks(symbol, on_tick):
            self.log("Gagal subscribe", "error")
            return False
        
        self.log("Menunggu 5 tick...")
        timeout = 15
        start = time.time()
        
        while tick_count < 5 and (time.time() - start) < timeout:
            time.sleep(0.5)
        
        # Unsubscribe
        self.ws.unsubscribe_ticks(symbol)
        
        if tick_count >= 5:
            self.log(f"Menerima {tick_count} tick dalam {time.time() - start:.1f}s", "success")
            return True
        else:
            self.log(f"Hanya menerima {tick_count} tick (timeout)", "warning")
            return tick_count > 0
    
    def test_proposal_and_buy(self, symbol: str = "R_100") -> bool:
        """Test proposal dan buy contract"""
        self.log("\n" + "="*60)
        self.log("TEST PROPOSAL DAN BUY CONTRACT")
        self.log("="*60)
        
        if not self.ws:
            return False
        
        # Test proposal
        self.log(f"Meminta proposal CALL pada {symbol}...")
        start = time.time()
        
        result = self.ws.buy_contract(
            contract_type="CALL",
            symbol=symbol,
            stake=0.35,
            duration=5,
            duration_unit="t"
        )
        
        elapsed = time.time() - start
        
        if result and result.get("contract_id"):
            contract_id = result.get("contract_id")
            buy_price = result.get("buy_price")
            payout = result.get("payout")
            
            self.log(f"Trade berhasil dalam {elapsed:.2f}s!", "success")
            self.log(f"  - Contract ID: {contract_id}")
            self.log(f"  - Buy Price: {buy_price}")
            self.log(f"  - Payout: {payout}")
            
            # Tunggu kontrak selesai
            self.log("Menunggu kontrak selesai...")
            time.sleep(8)  # 5 ticks + buffer
            
            return True
        else:
            self.log(f"Gagal membeli kontrak setelah {elapsed:.2f}s", "error")
            return False
    
    def test_strategy(self, strategy_name: str, num_trades: int = 2) -> Dict[str, Any]:
        """Test satu strategi"""
        self.log("\n" + "="*60)
        self.log(f"TEST STRATEGI: {strategy_name}")
        self.log("="*60)
        
        result = {
            "strategy": strategy_name,
            "status": "FAILED",
            "trades_attempted": 0,
            "trades_completed": 0,
            "wins": 0,
            "losses": 0,
            "profit": 0.0,
            "errors": [],
            "duration": 0
        }
        
        start_time = time.time()
        
        try:
            from trading import TradingManager, TradingConfig, StrategyType
            
            # Map strategy name to enum
            strategy_map = {
                "MULTI_INDICATOR": StrategyType.MULTI_INDICATOR,
                "LDP": StrategyType.LDP,
                "TICK_ANALYZER": StrategyType.TICK_ANALYZER,
                "TERMINAL": StrategyType.TERMINAL,
                "TICK_PICKER": StrategyType.TICK_PICKER,
                "DIGITPAD": StrategyType.DIGITPAD,
                "AMT": StrategyType.AMT,
                "SNIPER": StrategyType.SNIPER,
            }
            
            if strategy_name not in strategy_map:
                result["errors"].append(f"Strategi tidak dikenal: {strategy_name}")
                return result
            
            # Create config
            config = TradingConfig(
                symbol=TEST_CONFIG["symbol"],
                strategy=strategy_map[strategy_name],
                base_stake=TEST_CONFIG["base_stake"],
                duration=TEST_CONFIG["duration"],
                duration_unit=TEST_CONFIG["duration_unit"],
                max_trades=num_trades,
                use_martingale=False,  # Disable martingale untuk test
                take_profit=10.0,
                stop_loss=5.0,
            )
            
            # Create trading manager (ws is guaranteed to be connected at this point)
            if not self.ws:
                result["errors"].append("WebSocket tidak tersambung")
                return result
            manager = TradingManager(self.ws, config)
            
            # Track trades
            trades_completed = 0
            trade_results = []
            
            def on_trade_closed(data):
                nonlocal trades_completed
                trades_completed += 1
                trade_results.append(data)
                profit = data.get("profit", 0)
                self.log(f"  Trade {trades_completed}: {'WIN' if profit > 0 else 'LOSS'} ({profit:+.2f})")
            
            def on_error(msg):
                result["errors"].append(msg)
                self.log(f"  Error: {msg}", "error")
            
            def on_progress(data):
                msg = data.get("message", "")
                if msg:
                    self.log(f"  Progress: {msg}")
            
            manager.on_trade_closed = on_trade_closed
            manager.on_error = on_error
            manager.on_progress = on_progress
            
            # Start trading
            self.log(f"Memulai strategi {strategy_name}...")
            if not manager.start():
                result["errors"].append("Gagal memulai trading")
                return result
            
            result["trades_attempted"] = num_trades
            
            # Wait for trades to complete or timeout
            max_wait = num_trades * TEST_CONFIG["timeout_per_trade"]
            waited = 0
            
            while trades_completed < num_trades and waited < max_wait:
                time.sleep(5)
                waited += 5
                
                # Check status
                status = manager.get_status()
                if status.get("state") == "IDLE":
                    break
                
                # Log progress
                if waited % 30 == 0:
                    self.log(f"  Menunggu... (trades: {trades_completed}/{num_trades}, waktu: {waited}s)")
            
            # Stop trading
            manager.stop()
            
            # Collect results
            result["trades_completed"] = trades_completed
            result["wins"] = sum(1 for t in trade_results if t.get("profit", 0) > 0)
            result["losses"] = sum(1 for t in trade_results if t.get("profit", 0) <= 0)
            result["profit"] = sum(t.get("profit", 0) for t in trade_results)
            result["duration"] = time.time() - start_time
            
            if trades_completed > 0:
                result["status"] = "SUCCESS"
                self.log(f"Strategi {strategy_name}: {result['wins']}W/{result['losses']}L, Profit: {result['profit']:+.2f}", "success")
            else:
                result["status"] = "NO_TRADES"
                self.log(f"Strategi {strategy_name}: Tidak ada trade (mungkin tidak ada sinyal)", "warning")
            
        except Exception as e:
            result["errors"].append(str(e))
            result["duration"] = time.time() - start_time
            self.log(f"Error testing {strategy_name}: {e}", "error")
        
        return result
    
    def run_all_tests(self, strategies: Optional[List[str]] = None, trades_per_strategy: int = 2):
        """Jalankan semua test"""
        self.log("\n" + "="*70)
        self.log(" TEST SEMUA STRATEGI DERIV TRADING BOT")
        self.log("="*70)
        self.log(f"Waktu mulai: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Default strategies
        if strategies is None:
            strategies = [
                "MULTI_INDICATOR",
                "LDP",
                "TICK_ANALYZER",
            ]
        
        # Connect
        if not self.connect():
            self.log("Gagal terhubung, menghentikan test", "error")
            return
        
        try:
            # Test 1: Connection health
            if not self.test_connection_health():
                self.log("Koneksi tidak sehat, menghentikan test", "error")
                return
            
            # Test 2: Tick subscription
            if not self.test_tick_subscription():
                self.log("Tick subscription gagal, melanjutkan dengan hati-hati", "warning")
            
            # Test 3: Proposal and buy
            if not self.test_proposal_and_buy():
                self.log("Proposal/buy gagal, mungkin ada masalah koneksi", "warning")
            
            # Test 4: All strategies
            self.log("\n" + "="*60)
            self.log("TESTING SEMUA STRATEGI")
            self.log("="*60)
            
            for strategy in strategies:
                result = self.test_strategy(strategy, trades_per_strategy)
                self.results[strategy] = result
                
                # Short break between strategies
                if strategy != strategies[-1]:
                    self.log("Jeda 5 detik sebelum strategi berikutnya...")
                    time.sleep(5)
            
            # Print summary
            self.print_summary()
            
        finally:
            self.disconnect()
    
    def print_summary(self):
        """Print ringkasan hasil"""
        self.log("\n" + "="*70)
        self.log(" RINGKASAN HASIL TEST")
        self.log("="*70)
        
        total_trades = 0
        total_wins = 0
        total_losses = 0
        total_profit = 0.0
        
        for strategy, result in self.results.items():
            status_icon = "✅" if result["status"] == "SUCCESS" else "❌" if result["status"] == "FAILED" else "⚠️"
            self.log(f"\n{status_icon} {strategy}")
            self.log(f"   Status: {result['status']}")
            self.log(f"   Trades: {result['trades_completed']}/{result['trades_attempted']}")
            self.log(f"   W/L: {result['wins']}/{result['losses']}")
            self.log(f"   Profit: {result['profit']:+.2f}")
            self.log(f"   Durasi: {result['duration']:.1f}s")
            
            if result["errors"]:
                self.log(f"   Errors: {', '.join(result['errors'][:3])}")
            
            total_trades += result["trades_completed"]
            total_wins += result["wins"]
            total_losses += result["losses"]
            total_profit += result["profit"]
        
        self.log("\n" + "-"*70)
        self.log(f"TOTAL: {total_trades} trades, {total_wins}W/{total_losses}L, Profit: {total_profit:+.2f}")
        
        success_count = sum(1 for r in self.results.values() if r["status"] == "SUCCESS")
        self.log(f"Strategi berhasil: {success_count}/{len(self.results)}")


def main():
    parser = argparse.ArgumentParser(description="Test semua strategi trading Deriv")
    parser.add_argument("--token", type=str, help="Deriv API token", 
                        default=os.environ.get("DERIV_API_TOKEN", "074qAV4XaEqz8Jl"))
    parser.add_argument("--strategy", type=str, help="Test strategi tertentu saja")
    parser.add_argument("--trades", type=int, default=2, help="Jumlah trade per strategi")
    parser.add_argument("--all", action="store_true", help="Test semua strategi")
    parser.add_argument("--quick", action="store_true", help="Quick test (connection only)")
    
    args = parser.parse_args()
    
    tester = StrategyTester(args.token)
    
    if args.quick:
        # Quick connection test
        if tester.connect():
            tester.test_connection_health()
            tester.test_tick_subscription()
            tester.disconnect()
    elif args.strategy:
        # Test single strategy
        if tester.connect():
            tester.test_strategy(args.strategy.upper(), args.trades)
            tester.disconnect()
    elif args.all:
        # Test all strategies
        all_strategies = [
            "MULTI_INDICATOR",
            "LDP",
            "TICK_ANALYZER",
            "TERMINAL",
            "TICK_PICKER",
            "DIGITPAD",
            "AMT",
            "SNIPER",
        ]
        tester.run_all_tests(all_strategies, args.trades)
    else:
        # Default: test main strategies
        tester.run_all_tests(trades_per_strategy=args.trades)


if __name__ == "__main__":
    main()
