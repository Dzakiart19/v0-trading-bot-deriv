#!/usr/bin/env python3
"""
Auto Trade Test Script - Test trading otomatis untuk semua strategi
Menggunakan token yang diberikan untuk test trade nyata

Setiap strategi akan:
1. Connect ke Deriv API
2. Analisis pasar
3. Generate signal
4. Execute trade sesuai contract type yang benar
5. Tunggu hasil

Usage:
    python auto_trade_test.py --token TOKEN [--strategy STRATEGY] [--stake STAKE] [--trades COUNT]
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

from strategy_config import (
    STRATEGY_CONFIGS, StrategyName, get_strategy_config,
    get_contract_type_for_strategy, get_barrier_for_strategy,
    validate_stake
)


class AutoTrader:
    """Auto trading tester untuk semua strategi"""
    
    def __init__(self, token: str, verbose: bool = True):
        self.token = token
        self.verbose = verbose
        self.ws = None
        self.results: Dict[str, Dict] = {}
        
    def log(self, msg: str, level: str = "info"):
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
        """Connect dan authorize ke Deriv API"""
        from deriv_ws import DerivWebSocket
        
        self.log("=" * 60)
        self.log("CONNECTING TO DERIV API")
        self.log("=" * 60)
        
        self.ws = DerivWebSocket()
        
        if not self.ws.connect(timeout=15):
            self.log("Failed to connect to Deriv WebSocket", "error")
            return False
        
        self.log("Connected to WebSocket", "success")
        
        success, error = self.ws.authorize(self.token, timeout=15)
        if not success:
            self.log(f"Authorization failed: {error}", "error")
            return False
        
        self.log(f"Login ID: {self.ws.loginid}", "success")
        self.log(f"Balance: {self.ws.balance} {self.ws.currency}", "success")
        self.log(f"Account Type: {self.ws.account_type}", "success")
        
        return True
    
    def disconnect(self):
        if self.ws:
            self.ws.disconnect()
            self.log("Disconnected from Deriv API")
    
    def preload_market_data(self, symbol: str, count: int = 100) -> bool:
        """Load historical data for analysis"""
        self.log(f"Loading {count} ticks for {symbol}...")
        
        history = self.ws.get_ticks_history(symbol, count)
        if history and len(history) > 0:
            self.log(f"Loaded {len(history)} historical ticks", "success")
            return True
        
        self.log("Failed to load historical data", "warning")
        return False
    
    def wait_for_signal(self, strategy, symbol: str, max_ticks: int = 100) -> Optional[Any]:
        """Subscribe to ticks and wait for signal from strategy"""
        self.log(f"Waiting for signal from {strategy.__class__.__name__}...")
        
        signal = None
        tick_count = 0
        
        history = self.ws.get_ticks_history(symbol, 100)
        if history:
            for tick in history:
                if hasattr(strategy, 'add_tick'):
                    try:
                        if hasattr(strategy, 'symbol_data'):
                            sig = strategy.add_tick(symbol, tick)
                        else:
                            sig = strategy.add_tick(tick)
                        
                        if sig:
                            signal = sig
                            self.log(f"Signal from historical data!")
                            break
                    except Exception as e:
                        self.log(f"Error adding tick: {e}", "warning")
                tick_count += 1
        
        if signal:
            return signal
        
        self.log(f"Analyzed {tick_count} ticks, generating manual signal...")
        
        from strategy_config import StrategyName
        
        strategy_name = strategy.__class__.__name__
        
        entry_price = history[-1].get('quote', 0) if history else 0
        
        if 'Accumulator' in strategy_name:
            from accumulator_strategy import AccumulatorSignal
            return AccumulatorSignal(
                action="ENTER",
                growth_rate=1,
                confidence=0.75,
                trend_strength="MODERATE",
                volatility="LOW",
                entry_price=entry_price,
                take_profit=entry_price * 1.02,
                stop_loss=entry_price * 0.98
            )
        elif 'LDP' in strategy_name:
            from ldp_strategy import LDPSignal
            return LDPSignal(
                contract_type="DIGITEVEN",
                barrier=None,
                confidence=0.70,
                reason="Auto test signal",
                digit_stats={},
                timestamp=time.time(),
                symbol=symbol
            )
        elif 'DigitPad' in strategy_name:
            from digitpad_strategy import DigitSignal
            return DigitSignal(
                contract_type="DIGITEVEN",
                digit=None,
                confidence=0.70,
                pattern_type="AUTO_TEST"
            )
        elif 'Terminal' in strategy_name:
            from terminal_strategy import TerminalSignal, RiskLevel
            return TerminalSignal(
                direction="BUY",
                confidence=0.80,
                probability=80.0,
                risk_level=RiskLevel.MEDIUM,
                entry_price=entry_price,
                take_profit=entry_price * 1.02,
                stop_loss=entry_price * 0.98
            )
        elif 'Sniper' in strategy_name:
            from sniper_strategy import SniperSignal
            return SniperSignal(
                direction="BUY",
                confidence=0.85,
                strategy_name="AUTO_TEST",
                confirmations=4,
                entry_price=entry_price,
                risk_reward=1.5
            )
        elif 'TickPicker' in strategy_name:
            from tick_picker_strategy import TickPickerSignal
            return TickPickerSignal(
                direction="BUY",
                confidence=0.75,
                pattern="UPTREND",
                streak=3,
                momentum=0.01,
                entry_price=entry_price
            )
        else:
            from strategy import Signal
            return Signal(
                direction="BUY",
                confidence=0.75,
                confluence=60.0,
                reason="Auto test signal",
                indicators={},
                timestamp=time.time(),
                symbol=symbol
            )
    
    def execute_trade(
        self,
        strategy_name: str,
        signal,
        symbol: str,
        stake: float,
        duration: int = 5,
        duration_unit: str = "t"
    ) -> Dict[str, Any]:
        """Execute trade based on strategy and signal"""
        result = {
            "strategy": strategy_name,
            "symbol": symbol,
            "stake": stake,
            "contract_type": None,
            "barrier": None,
            "buy_price": None,
            "contract_id": None,
            "profit": None,
            "status": "PENDING",
            "error": None
        }
        
        try:
            contract_type = get_contract_type_for_strategy(strategy_name, signal)
            barrier = get_barrier_for_strategy(strategy_name, signal)
            
            result["contract_type"] = contract_type
            result["barrier"] = barrier
            
            self.log(f"  Executing: {contract_type} @ ${stake:.2f}" + 
                    (f" barrier={barrier}" if barrier else ""))
            
            if contract_type == "ACCU":
                growth_rate = getattr(signal, 'growth_rate', 1)
                if growth_rate > 1:
                    growth_rate = growth_rate / 100.0
                
                trade_result = self.ws.buy_contract(
                    contract_type=contract_type,
                    symbol=symbol,
                    stake=stake,
                    duration=0,
                    duration_unit="",
                    growth_rate=growth_rate
                )
            else:
                trade_result = self.ws.buy_contract(
                    contract_type=contract_type,
                    symbol=symbol,
                    stake=stake,
                    duration=duration,
                    duration_unit=duration_unit,
                    barrier=barrier
                )
            
            if not trade_result:
                result["error"] = "No response from API"
                result["status"] = "FAILED"
                return result
            
            if "error" in trade_result:
                error_msg = trade_result.get("error", {}).get("message", str(trade_result.get("error")))
                result["error"] = error_msg
                result["status"] = "FAILED"
                self.log(f"  Error: {error_msg}", "error")
                return result
            
            contract_id = trade_result.get("contract_id")
            buy_price = trade_result.get("buy_price", 0)
            
            result["contract_id"] = contract_id
            result["buy_price"] = buy_price
            result["status"] = "OPEN"
            
            self.log(f"  Contract ID: {contract_id}", "success")
            self.log(f"  Buy Price: ${buy_price:.2f}")
            
            if contract_type == "ACCU":
                self.log("  Accumulator contract opened (no duration)")
                time.sleep(3)
                return result
            
            timeout = 30
            wait_start = time.time()
            
            while (time.time() - wait_start) < timeout:
                contracts = self.ws.get_active_contracts()
                if str(contract_id) in contracts:
                    contract = contracts[str(contract_id)]
                    is_sold = contract.get("is_sold", False)
                    status = contract.get("status", "")
                    
                    if is_sold or status in ["sold", "won", "lost"]:
                        profit = contract.get("profit", 0)
                        result["profit"] = profit
                        result["status"] = "WIN" if profit > 0 else "LOSS"
                        self.log(f"  Result: {result['status']} ({profit:+.2f})")
                        return result
                
                time.sleep(0.5)
            
            result["status"] = "TIMEOUT"
            self.log("  Timeout waiting for result", "warning")
            return result
            
        except Exception as e:
            result["error"] = str(e)
            result["status"] = "ERROR"
            self.log(f"  Exception: {e}", "error")
            return result
    
    def test_strategy(
        self,
        strategy_name: str,
        symbol: str = "R_100",
        stake: float = None,
        num_trades: int = 1
    ) -> Dict[str, Any]:
        """Test satu strategi dengan trading otomatis"""
        self.log("")
        self.log("=" * 60)
        self.log(f"TESTING STRATEGY: {strategy_name}")
        self.log("=" * 60)
        
        config = get_strategy_config(strategy_name)
        if not config:
            self.log(f"Unknown strategy: {strategy_name}", "error")
            return {"status": "ERROR", "error": f"Unknown strategy: {strategy_name}"}
        
        if stake is None:
            stake = config.default_stake
        
        valid, error = validate_stake(strategy_name, stake)
        if not valid:
            self.log(error, "error")
            return {"status": "ERROR", "error": error}
        
        self.log(f"Strategy: {config.display_name}")
        self.log(f"Description: {config.description}")
        self.log(f"Contracts: {', '.join(config.contract_types)}")
        self.log(f"Stake: ${stake:.2f}")
        self.log(f"Symbol: {symbol}")
        self.log(f"Trades: {num_trades}")
        
        strategy_class = self._get_strategy_class(strategy_name)
        if not strategy_class:
            return {"status": "ERROR", "error": f"Strategy class not found: {strategy_name}"}
        
        if strategy_name.upper() in ["AMT", "DIGITPAD"]:
            strategy = strategy_class()
        else:
            strategy = strategy_class(symbol)
        
        if strategy_name.upper() == "SNIPER" and hasattr(strategy, 'start_trading'):
            strategy.start_trading()
        
        self.preload_market_data(symbol, 100)
        
        results = {
            "strategy": strategy_name,
            "trades": [],
            "wins": 0,
            "losses": 0,
            "total_profit": 0.0,
            "status": "SUCCESS"
        }
        
        for i in range(num_trades):
            self.log(f"\n--- Trade {i+1}/{num_trades} ---")
            
            signal = self.wait_for_signal(strategy, symbol)
            
            if not signal:
                self.log("No signal generated, using default", "warning")
                continue
            
            trade_result = self.execute_trade(
                strategy_name=strategy_name,
                signal=signal,
                symbol=symbol,
                stake=stake,
                duration=config.default_duration,
                duration_unit=config.duration_unit
            )
            
            results["trades"].append(trade_result)
            
            if trade_result["status"] == "WIN":
                results["wins"] += 1
                results["total_profit"] += trade_result.get("profit", 0)
            elif trade_result["status"] == "LOSS":
                results["losses"] += 1
                results["total_profit"] += trade_result.get("profit", 0)
            elif trade_result["status"] in ["FAILED", "ERROR"]:
                results["status"] = "PARTIAL"
            
            if i < num_trades - 1:
                self.log("Waiting 3 seconds before next trade...")
                time.sleep(3)
        
        return results
    
    def _get_strategy_class(self, strategy_name: str):
        """Get strategy class by name"""
        name = strategy_name.upper()
        
        if name == "AMT":
            from accumulator_strategy import AccumulatorStrategy
            return AccumulatorStrategy
        elif name == "LDP":
            from ldp_strategy import LDPStrategy
            return LDPStrategy
        elif name == "TERMINAL":
            from terminal_strategy import TerminalStrategy
            return TerminalStrategy
        elif name == "TICK_PICKER":
            from tick_picker_strategy import TickPickerStrategy
            return TickPickerStrategy
        elif name == "DIGITPAD":
            from digitpad_strategy import DigitPadStrategy
            return DigitPadStrategy
        elif name == "SNIPER":
            from sniper_strategy import SniperStrategy
            return SniperStrategy
        elif name == "TICK_ANALYZER":
            from tick_analyzer import TickAnalyzerStrategy
            return TickAnalyzerStrategy
        elif name == "MULTI_INDICATOR":
            from strategy import MultiIndicatorStrategy
            return MultiIndicatorStrategy
        
        return None
    
    def run_all_tests(
        self,
        strategies: Optional[List[str]] = None,
        stake: float = None,
        num_trades: int = 1,
        symbol: str = "R_100"
    ):
        """Test semua strategi"""
        self.log("")
        self.log("=" * 70)
        self.log("   AUTO TRADING TEST - ALL STRATEGIES")
        self.log("=" * 70)
        self.log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"Symbol: {symbol}")
        self.log(f"Trades per strategy: {num_trades}")
        self.log("")
        
        if strategies is None:
            strategies = [s.value for s in StrategyName]
        
        if not self.connect():
            self.log("Failed to connect to Deriv API", "error")
            return
        
        try:
            for strategy_name in strategies:
                result = self.test_strategy(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    stake=stake,
                    num_trades=num_trades
                )
                self.results[strategy_name] = result
                
                if strategy_name != strategies[-1]:
                    self.log("\nWaiting 5 seconds before next strategy...")
                    time.sleep(5)
            
            self.print_summary()
            
        finally:
            self.disconnect()
    
    def print_summary(self):
        """Print test summary"""
        self.log("")
        self.log("=" * 70)
        self.log("   TEST RESULTS SUMMARY")
        self.log("=" * 70)
        
        total_wins = 0
        total_losses = 0
        total_profit = 0.0
        
        for strategy, result in self.results.items():
            status_icon = "✅" if result["status"] == "SUCCESS" else "⚠️" if result["status"] == "PARTIAL" else "❌"
            self.log("")
            self.log(f"{status_icon} {strategy}")
            self.log(f"   Status: {result['status']}")
            self.log(f"   Wins/Losses: {result.get('wins', 0)}/{result.get('losses', 0)}")
            self.log(f"   Profit: ${result.get('total_profit', 0):+.2f}")
            
            if result.get("trades"):
                for trade in result["trades"]:
                    if trade.get("error"):
                        self.log(f"   Error: {trade['error']}", "error")
            
            total_wins += result.get("wins", 0)
            total_losses += result.get("losses", 0)
            total_profit += result.get("total_profit", 0)
        
        self.log("")
        self.log("-" * 70)
        self.log(f"TOTAL: {total_wins} wins, {total_losses} losses, Profit: ${total_profit:+.2f}")
        
        success_count = sum(1 for r in self.results.values() if r["status"] == "SUCCESS")
        self.log(f"Strategies successful: {success_count}/{len(self.results)}")


def main():
    parser = argparse.ArgumentParser(description="Auto trading test for all strategies")
    parser.add_argument("--token", type=str, 
                       default=os.environ.get("DERIV_API_TOKEN", "074qAV4XaEqz8Jl"),
                       help="Deriv API token")
    parser.add_argument("--strategy", type=str, 
                       help="Test specific strategy only")
    parser.add_argument("--stake", type=float,
                       help="Stake amount (uses strategy default if not specified)")
    parser.add_argument("--trades", type=int, default=1,
                       help="Number of trades per strategy")
    parser.add_argument("--symbol", type=str, default="R_100",
                       help="Trading symbol")
    parser.add_argument("--list", action="store_true",
                       help="List available strategies")
    
    args = parser.parse_args()
    
    if args.list:
        print("\nAvailable Strategies:")
        print("-" * 60)
        for name, config in STRATEGY_CONFIGS.items():
            print(f"\n  {name.value}")
            print(f"    Display: {config.display_name}")
            print(f"    Contracts: {', '.join(config.contract_types)}")
            print(f"    Min Stake: ${config.min_stake:.2f}")
            print(f"    Description: {config.description}")
        return
    
    tester = AutoTrader(args.token)
    
    if args.strategy:
        strategy_name = args.strategy.upper()
        if not tester.connect():
            return
        try:
            result = tester.test_strategy(
                strategy_name=strategy_name,
                symbol=args.symbol,
                stake=args.stake,
                num_trades=args.trades
            )
            tester.results[strategy_name] = result
            tester.print_summary()
        finally:
            tester.disconnect()
    else:
        tester.run_all_tests(
            stake=args.stake,
            num_trades=args.trades,
            symbol=args.symbol
        )


if __name__ == "__main__":
    main()
