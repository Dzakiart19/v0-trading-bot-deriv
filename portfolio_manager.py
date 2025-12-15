"""
Portfolio Manager - Complete portfolio tracking and analysis
Tracks equity curve, exposure, correlations, and performance metrics
"""

import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import threading
import math

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    direction: str
    entry_price: float
    stake: float
    entry_time: float
    contract_id: Optional[str] = None
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    strategy: str = "Unknown"


@dataclass
class TradeRecord:
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    stake: float
    profit: float
    entry_time: float
    exit_time: float
    strategy: str
    is_win: bool
    duration: float = 0.0
    
    def __post_init__(self):
        self.duration = self.exit_time - self.entry_time


@dataclass
class EquityPoint:
    timestamp: float
    balance: float
    drawdown: float
    drawdown_pct: float
    open_positions: int = 0


@dataclass
class SymbolStats:
    symbol: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0


@dataclass
class StrategyStats:
    strategy: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_profit: float = 0.0
    win_rate: float = 0.0
    avg_profit: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0


class PortfolioManager:
    """
    Comprehensive Portfolio Management System
    
    Features:
    - Real-time equity curve tracking
    - Position management
    - Symbol and strategy performance analysis
    - Drawdown monitoring
    - Exposure analysis
    - Correlation tracking
    - Risk metrics calculation
    """
    
    DATA_DIR = "logs/portfolio"
    EQUITY_HISTORY_SIZE = 10000
    
    def __init__(self, user_id: int, initial_balance: float = 0.0):
        self.user_id = user_id
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        
        os.makedirs(self.DATA_DIR, exist_ok=True)
        
        self.open_positions: Dict[str, Position] = {}
        self.trade_history: deque = deque(maxlen=1000)
        self.equity_curve: deque = deque(maxlen=self.EQUITY_HISTORY_SIZE)
        
        self.symbol_stats: Dict[str, SymbolStats] = defaultdict(lambda: SymbolStats(symbol=""))
        self.strategy_stats: Dict[str, StrategyStats] = defaultdict(lambda: StrategyStats(strategy=""))
        
        self.peak_balance = initial_balance
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.current_drawdown = 0.0
        self.current_drawdown_pct = 0.0
        
        self.total_trades = 0
        self.total_wins = 0
        self.total_losses = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.max_consecutive_wins = 0
        self.max_consecutive_losses = 0
        
        self.daily_returns: Dict[str, float] = {}
        
        self._lock = threading.RLock()
        self._load_state()
    
    def set_initial_balance(self, balance: float):
        """Set initial balance and reset tracking"""
        with self._lock:
            self.initial_balance = balance
            self.current_balance = balance
            self.peak_balance = balance
            self._record_equity_point()
    
    def update_balance(self, new_balance: float):
        """Update current balance and recalculate metrics"""
        with self._lock:
            self.current_balance = new_balance
            
            if new_balance > self.peak_balance:
                self.peak_balance = new_balance
            
            if self.peak_balance > 0:
                self.current_drawdown = self.peak_balance - new_balance
                self.current_drawdown_pct = self.current_drawdown / self.peak_balance
                
                if self.current_drawdown > self.max_drawdown:
                    self.max_drawdown = self.current_drawdown
                    self.max_drawdown_pct = self.current_drawdown_pct
            
            self._record_equity_point()
    
    def open_position(self, position: Position):
        """Record a new open position"""
        with self._lock:
            key = position.contract_id or f"{position.symbol}_{position.entry_time}"
            self.open_positions[key] = position
            self._record_equity_point()
            logger.info(f"Position opened: {position.symbol} {position.direction} ${position.stake}")
    
    def close_position(self, contract_id: str, exit_price: float, profit: float) -> Optional[TradeRecord]:
        """Close a position and record the trade"""
        with self._lock:
            position = self.open_positions.pop(contract_id, None)
            
            if position is None:
                for key, pos in list(self.open_positions.items()):
                    if key.startswith(contract_id) or contract_id in key:
                        position = self.open_positions.pop(key)
                        break
            
            if position is None:
                logger.warning(f"Position not found for contract_id: {contract_id}")
                return None
            
            is_win = profit > 0
            exit_time = time.time()
            
            trade = TradeRecord(
                symbol=position.symbol,
                direction=position.direction,
                entry_price=position.entry_price,
                exit_price=exit_price,
                stake=position.stake,
                profit=profit,
                entry_time=position.entry_time,
                exit_time=exit_time,
                strategy=position.strategy,
                is_win=is_win
            )
            
            self.trade_history.append(trade)
            self._update_statistics(trade)
            self._record_equity_point()
            self._save_state()
            
            return trade
    
    def record_trade(self, trade_data: Dict[str, Any]):
        """Record a completed trade from external data"""
        with self._lock:
            profit = trade_data.get("profit", 0)
            is_win = profit > 0
            
            trade = TradeRecord(
                symbol=trade_data.get("symbol", "Unknown"),
                direction=trade_data.get("direction", trade_data.get("contract_type", "Unknown")),
                entry_price=trade_data.get("entry_price", 0),
                exit_price=trade_data.get("exit_price", 0),
                stake=trade_data.get("stake", 0),
                profit=profit,
                entry_time=trade_data.get("entry_time", time.time()),
                exit_time=trade_data.get("exit_time", time.time()),
                strategy=trade_data.get("strategy", "Unknown"),
                is_win=is_win
            )
            
            self.trade_history.append(trade)
            self._update_statistics(trade)
            self._record_equity_point()
            self._save_state()
    
    def _update_statistics(self, trade: TradeRecord):
        """Update all statistics after a trade"""
        self.total_trades += 1
        
        if trade.is_win:
            self.total_wins += 1
            self.total_profit += trade.profit
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)
        else:
            self.total_losses += 1
            self.total_loss += abs(trade.profit)
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)
        
        self._update_symbol_stats(trade)
        self._update_strategy_stats(trade)
        self._update_daily_returns(trade)
    
    def _update_symbol_stats(self, trade: TradeRecord):
        """Update symbol-specific statistics"""
        symbol = trade.symbol
        
        if symbol not in self.symbol_stats:
            self.symbol_stats[symbol] = SymbolStats(symbol=symbol)
        
        stats = self.symbol_stats[symbol]
        stats.total_trades += 1
        
        if trade.is_win:
            stats.wins += 1
            stats.total_profit += trade.profit
        else:
            stats.losses += 1
            stats.total_loss += abs(trade.profit)
        
        stats.win_rate = (stats.wins / stats.total_trades * 100) if stats.total_trades > 0 else 0
        stats.profit_factor = (stats.total_profit / stats.total_loss) if stats.total_loss > 0 else float('inf')
        stats.avg_win = (stats.total_profit / stats.wins) if stats.wins > 0 else 0
        stats.avg_loss = (stats.total_loss / stats.losses) if stats.losses > 0 else 0
    
    def _update_strategy_stats(self, trade: TradeRecord):
        """Update strategy-specific statistics"""
        strategy = trade.strategy
        
        if strategy not in self.strategy_stats:
            self.strategy_stats[strategy] = StrategyStats(strategy=strategy)
        
        stats = self.strategy_stats[strategy]
        stats.total_trades += 1
        stats.total_profit += trade.profit
        
        if trade.is_win:
            stats.wins += 1
        else:
            stats.losses += 1
        
        stats.win_rate = (stats.wins / stats.total_trades * 100) if stats.total_trades > 0 else 0
        stats.avg_profit = stats.total_profit / stats.total_trades
    
    def _update_daily_returns(self, trade: TradeRecord):
        """Update daily returns tracking"""
        date_key = datetime.fromtimestamp(trade.exit_time).strftime("%Y-%m-%d")
        
        if date_key not in self.daily_returns:
            self.daily_returns[date_key] = 0.0
        
        self.daily_returns[date_key] += trade.profit
    
    def _record_equity_point(self):
        """Record current equity state"""
        point = EquityPoint(
            timestamp=time.time(),
            balance=self.current_balance,
            drawdown=self.current_drawdown,
            drawdown_pct=self.current_drawdown_pct,
            open_positions=len(self.open_positions)
        )
        self.equity_curve.append(point)
    
    def get_equity_curve(self, period: str = "all") -> List[Dict[str, Any]]:
        """Get equity curve data"""
        with self._lock:
            curve = list(self.equity_curve)
            
            if period != "all" and curve:
                now = time.time()
                if period == "day":
                    cutoff = now - 86400
                elif period == "week":
                    cutoff = now - 604800
                elif period == "month":
                    cutoff = now - 2592000
                else:
                    cutoff = 0
                
                curve = [p for p in curve if p.timestamp >= cutoff]
            
            return [asdict(p) for p in curve]
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get complete portfolio summary"""
        with self._lock:
            win_rate = (self.total_wins / self.total_trades * 100) if self.total_trades > 0 else 0
            profit_factor = (self.total_profit / self.total_loss) if self.total_loss > 0 else float('inf')
            net_profit = self.total_profit - self.total_loss
            roi = ((self.current_balance - self.initial_balance) / self.initial_balance * 100) if self.initial_balance > 0 else 0
            
            expectancy = 0
            if self.total_trades > 0:
                avg_win = self.total_profit / self.total_wins if self.total_wins > 0 else 0
                avg_loss = self.total_loss / self.total_losses if self.total_losses > 0 else 0
                expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss)
            
            sharpe = self._calculate_sharpe_ratio()
            
            return {
                "user_id": self.user_id,
                "initial_balance": self.initial_balance,
                "current_balance": self.current_balance,
                "peak_balance": self.peak_balance,
                "net_profit": net_profit,
                "roi_pct": roi,
                "total_trades": self.total_trades,
                "total_wins": self.total_wins,
                "total_losses": self.total_losses,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "expectancy": expectancy,
                "sharpe_ratio": sharpe,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct * 100,
                "current_drawdown": self.current_drawdown,
                "current_drawdown_pct": self.current_drawdown_pct * 100,
                "max_consecutive_wins": self.max_consecutive_wins,
                "max_consecutive_losses": self.max_consecutive_losses,
                "open_positions": len(self.open_positions),
                "total_profit": self.total_profit,
                "total_loss": self.total_loss
            }
    
    def get_symbol_performance(self) -> Dict[str, Dict[str, Any]]:
        """Get performance breakdown by symbol"""
        with self._lock:
            return {symbol: asdict(stats) for symbol, stats in self.symbol_stats.items()}
    
    def get_strategy_performance(self) -> Dict[str, Dict[str, Any]]:
        """Get performance breakdown by strategy"""
        with self._lock:
            return {strategy: asdict(stats) for strategy, stats in self.strategy_stats.items()}
    
    def get_exposure_analysis(self) -> Dict[str, Any]:
        """Analyze current portfolio exposure"""
        with self._lock:
            total_exposure = sum(p.stake for p in self.open_positions.values())
            
            symbol_exposure = defaultdict(float)
            direction_exposure = {"LONG": 0.0, "SHORT": 0.0}
            strategy_exposure = defaultdict(float)
            
            for pos in self.open_positions.values():
                symbol_exposure[pos.symbol] += pos.stake
                
                if pos.direction in ["BUY", "CALL", "LONG"]:
                    direction_exposure["LONG"] += pos.stake
                else:
                    direction_exposure["SHORT"] += pos.stake
                
                strategy_exposure[pos.strategy] += pos.stake
            
            exposure_pct = (total_exposure / self.current_balance * 100) if self.current_balance > 0 else 0
            
            return {
                "total_exposure": total_exposure,
                "exposure_pct": exposure_pct,
                "balance": self.current_balance,
                "symbol_exposure": dict(symbol_exposure),
                "direction_exposure": direction_exposure,
                "strategy_exposure": dict(strategy_exposure),
                "position_count": len(self.open_positions),
                "largest_position": max([p.stake for p in self.open_positions.values()], default=0)
            }
    
    def get_risk_metrics(self) -> Dict[str, Any]:
        """Calculate comprehensive risk metrics"""
        with self._lock:
            sharpe = self._calculate_sharpe_ratio()
            sortino = self._calculate_sortino_ratio()
            calmar = self._calculate_calmar_ratio()
            
            var_95 = self._calculate_var(0.95)
            var_99 = self._calculate_var(0.99)
            
            return {
                "sharpe_ratio": sharpe,
                "sortino_ratio": sortino,
                "calmar_ratio": calmar,
                "value_at_risk_95": var_95,
                "value_at_risk_99": var_99,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct * 100,
                "current_drawdown_pct": self.current_drawdown_pct * 100,
                "max_consecutive_losses": self.max_consecutive_losses,
                "avg_trade_size": self._calculate_avg_trade_size()
            }
    
    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe Ratio from daily returns"""
        if len(self.daily_returns) < 2:
            return 0.0
        
        returns = list(self.daily_returns.values())
        
        import statistics
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 1
        
        if std_return == 0:
            return 0.0
        
        daily_rf = risk_free_rate / 252
        sharpe = (mean_return - daily_rf) / std_return * math.sqrt(252)
        
        return round(sharpe, 2)
    
    def _calculate_sortino_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate Sortino Ratio using downside deviation"""
        if len(self.daily_returns) < 2:
            return 0.0
        
        returns = list(self.daily_returns.values())
        negative_returns = [r for r in returns if r < 0]
        
        if not negative_returns:
            return float('inf')
        
        import statistics
        mean_return = statistics.mean(returns)
        downside_std = statistics.stdev(negative_returns) if len(negative_returns) > 1 else 1
        
        if downside_std == 0:
            return 0.0
        
        daily_rf = risk_free_rate / 252
        sortino = (mean_return - daily_rf) / downside_std * math.sqrt(252)
        
        return round(sortino, 2)
    
    def _calculate_calmar_ratio(self) -> float:
        """Calculate Calmar Ratio (annualized return / max drawdown)"""
        if self.max_drawdown_pct == 0 or self.initial_balance == 0:
            return 0.0
        
        total_return = (self.current_balance - self.initial_balance) / self.initial_balance
        
        if len(self.daily_returns) > 0:
            days = len(self.daily_returns)
            annualized_return = total_return * (252 / days) if days > 0 else total_return
        else:
            annualized_return = total_return
        
        calmar = annualized_return / self.max_drawdown_pct if self.max_drawdown_pct > 0 else 0
        
        return round(calmar, 2)
    
    def _calculate_var(self, confidence: float = 0.95) -> float:
        """Calculate Value at Risk at given confidence level"""
        if len(self.trade_history) < 10:
            return 0.0
        
        returns = [t.profit for t in self.trade_history]
        returns.sort()
        
        index = int((1 - confidence) * len(returns))
        var = abs(returns[index]) if index < len(returns) else 0
        
        return round(var, 2)
    
    def _calculate_avg_trade_size(self) -> float:
        """Calculate average trade size"""
        if not self.trade_history:
            return 0.0
        
        total_stake = sum(t.stake for t in self.trade_history)
        return total_stake / len(self.trade_history)
    
    def get_recent_trades(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent trade history"""
        with self._lock:
            trades = list(self.trade_history)[-limit:]
            return [asdict(t) for t in reversed(trades)]
    
    def _save_state(self):
        """Save portfolio state to file"""
        try:
            state = {
                "user_id": self.user_id,
                "initial_balance": self.initial_balance,
                "current_balance": self.current_balance,
                "peak_balance": self.peak_balance,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct,
                "total_trades": self.total_trades,
                "total_wins": self.total_wins,
                "total_losses": self.total_losses,
                "total_profit": self.total_profit,
                "total_loss": self.total_loss,
                "max_consecutive_wins": self.max_consecutive_wins,
                "max_consecutive_losses": self.max_consecutive_losses,
                "symbol_stats": {k: asdict(v) for k, v in self.symbol_stats.items()},
                "strategy_stats": {k: asdict(v) for k, v in self.strategy_stats.items()},
                "daily_returns": self.daily_returns,
                "trade_history": [asdict(t) for t in list(self.trade_history)[-100:]]
            }
            
            filename = os.path.join(self.DATA_DIR, f"portfolio_{self.user_id}.json")
            with open(filename, 'w') as f:
                json.dump(state, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save portfolio state: {e}")
    
    def _load_state(self):
        """Load portfolio state from file"""
        try:
            filename = os.path.join(self.DATA_DIR, f"portfolio_{self.user_id}.json")
            if not os.path.exists(filename):
                return
            
            with open(filename, 'r') as f:
                state = json.load(f)
            
            self.initial_balance = state.get("initial_balance", 0)
            self.current_balance = state.get("current_balance", 0)
            self.peak_balance = state.get("peak_balance", 0)
            self.max_drawdown = state.get("max_drawdown", 0)
            self.max_drawdown_pct = state.get("max_drawdown_pct", 0)
            self.total_trades = state.get("total_trades", 0)
            self.total_wins = state.get("total_wins", 0)
            self.total_losses = state.get("total_losses", 0)
            self.total_profit = state.get("total_profit", 0)
            self.total_loss = state.get("total_loss", 0)
            self.max_consecutive_wins = state.get("max_consecutive_wins", 0)
            self.max_consecutive_losses = state.get("max_consecutive_losses", 0)
            self.daily_returns = state.get("daily_returns", {})
            
            for symbol, stats_dict in state.get("symbol_stats", {}).items():
                self.symbol_stats[symbol] = SymbolStats(**stats_dict)
            
            for strategy, stats_dict in state.get("strategy_stats", {}).items():
                self.strategy_stats[strategy] = StrategyStats(**stats_dict)
            
            for trade_dict in state.get("trade_history", []):
                self.trade_history.append(TradeRecord(**trade_dict))
            
            logger.info(f"Portfolio state loaded for user {self.user_id}")
            
        except Exception as e:
            logger.error(f"Failed to load portfolio state: {e}")
    
    def reset(self):
        """Reset all portfolio data"""
        with self._lock:
            self.open_positions.clear()
            self.trade_history.clear()
            self.equity_curve.clear()
            self.symbol_stats.clear()
            self.strategy_stats.clear()
            self.daily_returns.clear()
            
            self.peak_balance = self.initial_balance
            self.max_drawdown = 0
            self.max_drawdown_pct = 0
            self.current_drawdown = 0
            self.current_drawdown_pct = 0
            
            self.total_trades = 0
            self.total_wins = 0
            self.total_losses = 0
            self.total_profit = 0
            self.total_loss = 0
            
            self.consecutive_wins = 0
            self.consecutive_losses = 0
            self.max_consecutive_wins = 0
            self.max_consecutive_losses = 0
            
            self._save_state()
            logger.info(f"Portfolio reset for user {self.user_id}")


class PortfolioManagerFactory:
    """Factory for creating and managing portfolio managers per user"""
    
    _instances: Dict[int, PortfolioManager] = {}
    _lock = threading.Lock()
    
    @classmethod
    def get_manager(cls, user_id: int, initial_balance: float = 0.0) -> PortfolioManager:
        """Get or create a portfolio manager for a user"""
        with cls._lock:
            if user_id not in cls._instances:
                cls._instances[user_id] = PortfolioManager(user_id, initial_balance)
            elif initial_balance > 0:
                cls._instances[user_id].set_initial_balance(initial_balance)
            return cls._instances[user_id]
    
    @classmethod
    def remove_manager(cls, user_id: int):
        """Remove a portfolio manager"""
        with cls._lock:
            cls._instances.pop(user_id, None)
