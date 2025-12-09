"""
Analytics - Session analytics with detailed metrics and export
"""

import json
import csv
import os
import time
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class TradeEntry:
    """Single trade entry for journaling"""
    date: str
    time: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    stake: float
    payout: float
    profit: float
    result: str  # WIN or LOSS
    martingale_level: int
    balance_before: float
    balance_after: float
    win_rate: float
    strategy: str
    confidence: float
    confluence: float

class TradingAnalytics:
    """
    Trading Analytics System
    
    Features:
    - Rolling win rate calculation
    - Max drawdown tracking
    - Martingale recovery success rate
    - Best RSI range identification
    - Hourly profit tracking
    - Export to JSON and CSV
    """
    
    ROLLING_WINDOW = 20
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        self.trades: deque = deque(maxlen=500)
        self.session_start = None
        self.session_trades = 0
        
        # Analytics data
        self.hourly_profits: Dict[int, float] = {h: 0.0 for h in range(24)}
        self.rsi_performance: Dict[str, Dict[str, int]] = {}
        self.martingale_stats = {
            "recovery_attempts": 0,
            "recovery_success": 0,
            "max_level_reached": 0
        }
        
        # Ensure log directory exists
        os.makedirs(log_dir, exist_ok=True)
    
    def start_session(self):
        """Start new analytics session"""
        self.session_start = datetime.now()
        self.session_trades = 0
        self.hourly_profits = {h: 0.0 for h in range(24)}
        logger.info("Analytics session started")
    
    def end_session(self) -> Dict[str, Any]:
        """End analytics session and return summary"""
        summary = self.get_session_summary()
        
        # Export session data if there were trades
        if self.session_trades > 0:
            try:
                self.export_to_json()
            except Exception as e:
                logger.error(f"Failed to export session: {e}")
        
        # Reset session state
        session_duration = None
        if self.session_start:
            session_duration = (datetime.now() - self.session_start).total_seconds()
        
        self.session_start = None
        self.session_trades = 0
        
        summary["session_duration_seconds"] = session_duration
        logger.info(f"Analytics session ended: {self.session_trades} trades")
        
        return summary
    
    def record_trade(self, trade: TradeEntry):
        """Record a trade for analytics"""
        self.trades.append(trade)
        self.session_trades += 1
        
        # Update hourly profits
        hour = datetime.now().hour
        self.hourly_profits[hour] += trade.profit
        
        # Track RSI performance
        # This would integrate with strategy to get RSI at entry
        
        # Write to CSV
        self._write_to_csv(trade)
        
        logger.debug(f"Trade recorded: {trade.result} | Profit: {trade.profit:+.2f}")
    
    def record_martingale_attempt(self, success: bool, level: int):
        """Record martingale recovery attempt"""
        self.martingale_stats["recovery_attempts"] += 1
        if success:
            self.martingale_stats["recovery_success"] += 1
        self.martingale_stats["max_level_reached"] = max(
            self.martingale_stats["max_level_reached"],
            level
        )
    
    def get_rolling_win_rate(self) -> float:
        """Calculate rolling win rate over last N trades"""
        if len(self.trades) == 0:
            return 0.0
        
        recent = list(self.trades)[-self.ROLLING_WINDOW:]
        wins = sum(1 for t in recent if t.result == "WIN")
        return (wins / len(recent)) * 100
    
    def get_max_drawdown(self) -> float:
        """Calculate maximum drawdown from trade history"""
        if len(self.trades) < 2:
            return 0.0
        
        balances = [t.balance_after for t in self.trades]
        peak = balances[0]
        max_dd = 0.0
        
        for balance in balances:
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        
        return max_dd * 100
    
    def get_profit_factor(self) -> float:
        """Calculate profit factor (gross profit / gross loss)"""
        gross_profit = sum(t.profit for t in self.trades if t.profit > 0)
        gross_loss = abs(sum(t.profit for t in self.trades if t.profit < 0))
        
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 0.0
        
        return gross_profit / gross_loss
    
    def get_best_trading_hours(self) -> List[int]:
        """Get hours with best profitability"""
        sorted_hours = sorted(
            self.hourly_profits.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [h for h, p in sorted_hours[:3] if p > 0]
    
    def get_martingale_success_rate(self) -> float:
        """Get martingale recovery success rate"""
        if self.martingale_stats["recovery_attempts"] == 0:
            return 0.0
        
        return (
            self.martingale_stats["recovery_success"] /
            self.martingale_stats["recovery_attempts"] * 100
        )
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get comprehensive session summary"""
        if len(self.trades) == 0:
            return {"status": "no_trades"}
        
        total_profit = sum(t.profit for t in self.trades)
        wins = sum(1 for t in self.trades if t.result == "WIN")
        losses = len(self.trades) - wins
        
        return {
            "session_start": self.session_start.isoformat() if self.session_start else None,
            "total_trades": len(self.trades),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(self.trades)) * 100,
            "rolling_win_rate": self.get_rolling_win_rate(),
            "total_profit": total_profit,
            "profit_factor": self.get_profit_factor(),
            "max_drawdown": self.get_max_drawdown(),
            "best_hours": self.get_best_trading_hours(),
            "martingale_success_rate": self.get_martingale_success_rate(),
            "hourly_profits": self.hourly_profits
        }
    
    def _write_to_csv(self, trade: TradeEntry):
        """Write trade to CSV file (atomic write)"""
        date_str = datetime.now().strftime("%Y%m%d")
        filename = os.path.join(self.log_dir, f"trades_{date_str}.csv")
        
        # Check if file exists to determine if we need header
        file_exists = os.path.exists(filename)
        
        # Write to temp file first
        temp_file = filename + ".tmp"
        
        try:
            with open(temp_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                if not file_exists:
                    # Write header
                    writer.writerow([
                        "Date", "Time", "Symbol", "Direction", "Entry", "Exit",
                        "Stake", "Payout", "Profit", "Result", "Martingale Level",
                        "Balance Before", "Balance After", "Win Rate",
                        "Strategy", "Confidence", "Confluence"
                    ])
                
                writer.writerow([
                    trade.date, trade.time, trade.symbol, trade.direction,
                    trade.entry_price, trade.exit_price, trade.stake,
                    trade.payout, trade.profit, trade.result,
                    trade.martingale_level, trade.balance_before,
                    trade.balance_after, f"{trade.win_rate:.1f}%",
                    trade.strategy, trade.confidence, trade.confluence
                ])
            
            # Atomic rename
            if file_exists:
                # Append to existing
                with open(filename, 'a', encoding='utf-8') as dest:
                    with open(temp_file, 'r', encoding='utf-8') as src:
                        dest.write(src.read())
                os.remove(temp_file)
            else:
                os.rename(temp_file, filename)
                
        except Exception as e:
            logger.error(f"Error writing to CSV: {e}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
    
    def export_to_json(self) -> str:
        """Export analytics to JSON file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.log_dir, f"analytics_{timestamp}.json")
        
        data = {
            "export_time": datetime.now().isoformat(),
            "session_summary": self.get_session_summary(),
            "martingale_stats": self.martingale_stats,
            "trades": [asdict(t) for t in self.trades]
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Analytics exported to {filename}")
        return filename
    
    def cleanup_old_logs(self, days: int = 1):
        """Remove log files older than specified days"""
        import glob
        
        cutoff = time.time() - (days * 86400)
        
        for pattern in ["trades_*.csv", "analytics_*.json", "session_*.txt"]:
            for filepath in glob.glob(os.path.join(self.log_dir, pattern)):
                if os.path.getmtime(filepath) < cutoff:
                    try:
                        os.remove(filepath)
                        logger.debug(f"Removed old log: {filepath}")
                    except Exception as e:
                        logger.error(f"Error removing {filepath}: {e}")
