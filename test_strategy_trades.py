#!/usr/bin/env python3
"""
Test Strategi Trading - Script untuk menguji TRADE NYATA semua strategi
dengan kontrak yang benar sesuai cara kerja masing-masing.

Kontrak yang digunakan per strategi:
1. MULTI_INDICATOR - CALL/PUT (Rise/Fall)
2. LDP - DIGITDIFF/DIGITOVER/DIGITUNDER/DIGITMATCH/DIGITEVEN/DIGITODD
3. TICK_ANALYZER - CALL/PUT (Rise/Fall)
4. TERMINAL - CALL/PUT (Rise/Fall)
5. TICK_PICKER - CALL/PUT (Rise/Fall)
6. DIGITPAD - DIGITDIFF/DIGITMATCH/DIGITEVEN/DIGITODD
7. AMT - ACCU (Accumulator)
8. SNIPER - CALL/PUT (Rise/Fall)

Penggunaan:
    python test_strategy_trades.py [--token TOKEN] [--strategy STRATEGY]
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

TEST_CONFIG = {
    "symbol": "R_100",
    "base_stake": 0.35,
    "duration": 5,
    "duration_unit": "t",
    "wait_result_timeout": 30,
}

STRATEGY_CONTRACT_MAP = {
    "MULTI_INDICATOR": {
        "contracts": ["CALL", "PUT"],
        "description": "Rise/Fall based on multi-indicator confluence",
        "needs_barrier": False,
    },
    "LDP": {
        "contracts": ["DIGITDIFF", "DIGITOVER", "DIGITUNDER", "DIGITMATCH", "DIGITEVEN", "DIGITODD"],
        "description": "Last digit prediction (digit contracts)",
        "needs_barrier": True,
        "test_contract": "DIGITDIFF",
        "test_barrier": "5",
    },
    "TICK_ANALYZER": {
        "contracts": ["CALL", "PUT"],
        "description": "Tick pattern analysis for Rise/Fall",
        "needs_barrier": False,
    },
    "TERMINAL": {
        "contracts": ["CALL", "PUT"],
        "description": "Smart analysis 80%+ probability for Rise/Fall",
        "needs_barrier": False,
    },
    "TICK_PICKER": {
        "contracts": ["CALL", "PUT"],
        "description": "Tick pattern picker for Rise/Fall",
        "needs_barrier": False,
    },
    "DIGITPAD": {
        "contracts": ["DIGITDIFF", "DIGITMATCH", "DIGITEVEN", "DIGITODD"],
        "description": "Digit frequency analysis (digit contracts)",
        "needs_barrier": True,
        "test_contract": "DIGITEVEN",
        "test_barrier": None,
    },
    "AMT": {
        "contracts": ["ACCU"],
        "description": "Accumulator contract with growth rate",
        "needs_barrier": False,
        "needs_growth_rate": True,
    },
    "SNIPER": {
        "contracts": ["CALL", "PUT"],
        "description": "Ultra-selective high confidence Rise/Fall",
        "needs_barrier": False,
    },
}


class StrategyTrader:
    """Tester untuk trade nyata semua strategi"""
    
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
                logger.info(f"[OK] {msg}")
            else:
                logger.info(msg)
    
    def connect(self) -> bool:
        """Koneksi dan otorisasi ke Deriv API"""
        from deriv_ws import DerivWebSocket
        
        self.log("=" * 60)
        self.log("KONEKSI KE DERIV API")
        self.log("=" * 60)
        
        self.ws = DerivWebSocket()
        
        if not self.ws.connect(timeout=15):
            self.log("Gagal terhubung ke Deriv WebSocket", "error")
            return False
        
        self.log("Terhubung ke WebSocket", "success")
        
        success, error = self.ws.authorize(self.token, timeout=15)
        if not success:
            self.log(f"Gagal otorisasi: {error}", "error")
            return False
        
        self.log(f"Login: {self.ws.loginid}", "success")
        self.log(f"Saldo: {self.ws.balance} {self.ws.currency}", "success")
        self.log(f"Tipe Akun: {self.ws.account_type}", "success")
        
        return True
    
    def disconnect(self):
        if self.ws:
            self.ws.disconnect()
            self.log("Terputus dari Deriv API")
    
    def execute_trade(
        self,
        contract_type: str,
        symbol: str,
        stake: float,
        duration: int = 5,
        duration_unit: str = "t",
        barrier: Optional[str] = None,
        growth_rate: Optional[float] = None
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Execute trade dan tunggu hasilnya
        
        Returns:
            Tuple[success, result_dict]
        """
        result = {
            "contract_type": contract_type,
            "symbol": symbol,
            "stake": stake,
            "barrier": barrier,
            "growth_rate": growth_rate,
            "buy_price": None,
            "contract_id": None,
            "profit": None,
            "status": "FAILED",
            "error": None,
            "duration_ms": 0
        }
        
        start_time = time.time()
        
        try:
            self.log(f"  Eksekusi: {contract_type} @ ${stake:.2f}" + 
                    (f" barrier={barrier}" if barrier else "") +
                    (f" growth={growth_rate}" if growth_rate else ""))
            
            trade_result = self.ws.buy_contract(
                contract_type=contract_type,
                symbol=symbol,
                stake=stake,
                duration=duration,
                duration_unit=duration_unit,
                barrier=barrier,
                growth_rate=growth_rate
            )
            
            if not trade_result:
                result["error"] = "Tidak ada respons dari API"
                result["duration_ms"] = int((time.time() - start_time) * 1000)
                return False, result
            
            if "error" in trade_result:
                error_msg = trade_result.get("error", {}).get("message", str(trade_result.get("error")))
                result["error"] = error_msg
                result["duration_ms"] = int((time.time() - start_time) * 1000)
                self.log(f"  Error: {error_msg}", "error")
                return False, result
            
            contract_id = trade_result.get("contract_id")
            buy_price = trade_result.get("buy_price", 0)
            
            result["contract_id"] = contract_id
            result["buy_price"] = buy_price
            result["payout"] = trade_result.get("payout", 0)
            
            self.log(f"  Contract ID: {contract_id}", "success")
            self.log(f"  Buy Price: ${buy_price:.2f}")
            
            if contract_type == "ACCU":
                time.sleep(3)
                result["status"] = "OPEN"
                result["duration_ms"] = int((time.time() - start_time) * 1000)
                return True, result
            
            timeout = TEST_CONFIG["wait_result_timeout"]
            wait_start = time.time()
            
            while (time.time() - wait_start) < timeout:
                contracts = self.ws.get_active_contracts()
                if str(contract_id) in contracts:
                    contract = contracts[str(contract_id)]
                    is_sold = contract.get("is_sold", False)
                    status = contract.get("status", "")
                    
                    if is_sold or status in ["sold", "won", "lost"]:
                        profit = contract.get("profit", 0)
                        sell_price = contract.get("sell_price", 0)
                        
                        result["profit"] = profit
                        result["sell_price"] = sell_price
                        result["status"] = "WIN" if profit > 0 else "LOSS"
                        result["duration_ms"] = int((time.time() - start_time) * 1000)
                        
                        self.log(f"  Hasil: {result['status']} ({profit:+.2f})")
                        return True, result
                
                time.sleep(0.5)
            
            result["status"] = "TIMEOUT"
            result["duration_ms"] = int((time.time() - start_time) * 1000)
            self.log(f"  Timeout menunggu hasil", "warning")
            return True, result
            
        except Exception as e:
            result["error"] = str(e)
            result["duration_ms"] = int((time.time() - start_time) * 1000)
            self.log(f"  Exception: {e}", "error")
            return False, result
    
    def test_strategy_contract(self, strategy_name: str) -> Dict[str, Any]:
        """
        Test trade nyata untuk satu strategi
        """
        self.log("")
        self.log("=" * 60)
        self.log(f"TEST STRATEGI: {strategy_name}")
        self.log("=" * 60)
        
        if strategy_name not in STRATEGY_CONTRACT_MAP:
            self.log(f"Strategi tidak dikenal: {strategy_name}", "error")
            return {"status": "UNKNOWN", "error": f"Unknown strategy: {strategy_name}"}
        
        config = STRATEGY_CONTRACT_MAP[strategy_name]
        
        self.log(f"Deskripsi: {config['description']}")
        self.log(f"Kontrak yang didukung: {', '.join(config['contracts'])}")
        
        result = {
            "strategy": strategy_name,
            "description": config["description"],
            "trades": [],
            "success": 0,
            "failed": 0,
            "wins": 0,
            "losses": 0,
            "total_profit": 0.0,
            "status": "PENDING"
        }
        
        if strategy_name == "AMT":
            self.log("")
            self.log("  [AMT ACCUMULATOR TEST]")
            
            success, trade_result = self.execute_trade(
                contract_type="ACCU",
                symbol=TEST_CONFIG["symbol"],
                stake=TEST_CONFIG["base_stake"],
                duration=0,
                duration_unit="",
                growth_rate=0.01
            )
            
            result["trades"].append(trade_result)
            
            if success and trade_result.get("contract_id"):
                result["success"] += 1
                result["status"] = "SUCCESS"
                self.log(f"  Accumulator berhasil dibuka!", "success")
            else:
                result["failed"] += 1
                result["status"] = "FAILED"
                self.log(f"  Accumulator GAGAL: {trade_result.get('error')}", "error")
            
            return result
        
        contracts_to_test = []
        
        if config.get("test_contract"):
            contracts_to_test.append({
                "type": config["test_contract"],
                "barrier": config.get("test_barrier")
            })
        else:
            contracts_to_test.append({
                "type": config["contracts"][0],
                "barrier": None
            })
        
        for contract in contracts_to_test:
            self.log("")
            self.log(f"  [{contract['type']}]")
            
            success, trade_result = self.execute_trade(
                contract_type=contract["type"],
                symbol=TEST_CONFIG["symbol"],
                stake=TEST_CONFIG["base_stake"],
                duration=TEST_CONFIG["duration"],
                duration_unit=TEST_CONFIG["duration_unit"],
                barrier=contract["barrier"]
            )
            
            result["trades"].append(trade_result)
            
            if success and trade_result.get("contract_id"):
                result["success"] += 1
                
                if trade_result.get("profit") is not None:
                    result["total_profit"] += trade_result["profit"]
                    if trade_result["profit"] > 0:
                        result["wins"] += 1
                    else:
                        result["losses"] += 1
            else:
                result["failed"] += 1
        
        if result["success"] > 0:
            result["status"] = "SUCCESS"
        else:
            result["status"] = "FAILED"
        
        return result
    
    def run_all_tests(self, strategies: Optional[List[str]] = None):
        """Jalankan test untuk semua strategi"""
        self.log("")
        self.log("=" * 70)
        self.log("   TEST TRADE NYATA SEMUA STRATEGI")
        self.log("=" * 70)
        self.log(f"Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"Symbol: {TEST_CONFIG['symbol']}")
        self.log(f"Stake: ${TEST_CONFIG['base_stake']}")
        self.log("")
        
        if strategies is None:
            strategies = list(STRATEGY_CONTRACT_MAP.keys())
        
        if not self.connect():
            self.log("Gagal terhubung ke Deriv API", "error")
            return
        
        try:
            for strategy in strategies:
                result = self.test_strategy_contract(strategy)
                self.results[strategy] = result
                
                if strategy != strategies[-1]:
                    self.log("")
                    self.log("Jeda 5 detik sebelum strategi berikutnya...")
                    time.sleep(5)
            
            self.print_summary()
            
        finally:
            self.disconnect()
    
    def print_summary(self):
        """Cetak ringkasan hasil"""
        self.log("")
        self.log("=" * 70)
        self.log("   RINGKASAN HASIL TEST")
        self.log("=" * 70)
        
        total_success = 0
        total_failed = 0
        total_profit = 0.0
        
        for strategy, result in self.results.items():
            status_icon = "[OK]" if result["status"] == "SUCCESS" else "[GAGAL]"
            self.log("")
            self.log(f"{status_icon} {strategy}")
            self.log(f"   Status: {result['status']}")
            self.log(f"   Trades berhasil: {result['success']}")
            self.log(f"   Trades gagal: {result['failed']}")
            
            if result.get("wins") or result.get("losses"):
                self.log(f"   Win/Loss: {result.get('wins', 0)}/{result.get('losses', 0)}")
                self.log(f"   Profit: ${result.get('total_profit', 0):+.2f}")
            
            if result.get("trades"):
                for trade in result["trades"]:
                    if trade.get("error"):
                        self.log(f"   Error: {trade['error']}", "error")
            
            total_success += result["success"]
            total_failed += result["failed"]
            total_profit += result.get("total_profit", 0)
        
        self.log("")
        self.log("-" * 70)
        self.log(f"TOTAL: {total_success} berhasil, {total_failed} gagal, Profit: ${total_profit:+.2f}")
        
        success_count = sum(1 for r in self.results.values() if r["status"] == "SUCCESS")
        self.log(f"Strategi berhasil: {success_count}/{len(self.results)}")
        
        failed_strategies = [s for s, r in self.results.items() if r["status"] == "FAILED"]
        if failed_strategies:
            self.log("")
            self.log("STRATEGI YANG GAGAL:", "error")
            for s in failed_strategies:
                error = self.results[s].get("trades", [{}])[0].get("error", "Unknown")
                self.log(f"  - {s}: {error}", "error")


def main():
    parser = argparse.ArgumentParser(description="Test trade nyata untuk semua strategi")
    parser.add_argument("--token", type=str, 
                       default=os.environ.get("DERIV_API_TOKEN", "074qAV4XaEqz8Jl"),
                       help="Deriv API token")
    parser.add_argument("--strategy", type=str, 
                       help="Test strategi tertentu saja (MULTI_INDICATOR, LDP, dll)")
    parser.add_argument("--list", action="store_true",
                       help="Tampilkan daftar strategi yang tersedia")
    
    args = parser.parse_args()
    
    if args.list:
        print("\nDaftar Strategi yang Tersedia:")
        print("-" * 60)
        for name, config in STRATEGY_CONTRACT_MAP.items():
            print(f"  {name}")
            print(f"    Kontrak: {', '.join(config['contracts'])}")
            print(f"    Deskripsi: {config['description']}")
            print()
        return
    
    tester = StrategyTrader(args.token)
    
    if args.strategy:
        strategy_name = args.strategy.upper()
        if strategy_name not in STRATEGY_CONTRACT_MAP:
            print(f"Error: Strategi '{strategy_name}' tidak dikenal")
            print(f"Strategi yang tersedia: {', '.join(STRATEGY_CONTRACT_MAP.keys())}")
            return
        tester.run_all_tests([strategy_name])
    else:
        tester.run_all_tests()


if __name__ == "__main__":
    main()
