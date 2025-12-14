"""
Paper Trading / Backtesting Module
Allows testing strategies without real money
"""

import logging
import time
import random
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class PaperTradingMode(Enum):
    PAPER = "PAPER"  # Simulated live trading
    BACKTEST = "BACKTEST"  # Historical data testing


@dataclass
class PaperTrade:
    """Represents a simulated trade"""
    trade_id: str
    symbol: str
    contract_type: str
    stake: float
    entry_price: float
    entry_time: datetime
    duration: int
    duration_unit: str
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    payout: float = 0.0
    profit: float = 0.0
    is_win: bool = False
    is_closed: bool = False


@dataclass
class BacktestResult:
    """Results from a backtest run"""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_profit: float = 0.0
    max_drawdown: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_profit_per_trade: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    trades: List[PaperTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    start_balance: float = 0.0
    end_balance: float = 0.0
    duration_seconds: float = 0.0


class PaperTradingManager:
    """
    Paper Trading Manager - Simulates trading without real money
    
    Features:
    - Simulated balance tracking
    - Realistic trade execution with configurable win rate
    - Trade history and statistics
    - Equity curve generation
    - Backtesting support with historical data
    """
    
    def __init__(self, initial_balance: float = 10000.0, payout_percent: float = 85.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.payout_percent = payout_percent
        
        self.mode = PaperTradingMode.PAPER
        self.is_running = False
        
        self.trades: List[PaperTrade] = []
        self.active_trade: Optional[PaperTrade] = None
        self.equity_curve: List[float] = [initial_balance]
        
        self.session_trades = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_profit = 0.0
        
        self.max_drawdown = 0.0
        self.peak_balance = initial_balance
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.max_consecutive_wins = 0
        self.max_consecutive_losses = 0
        
        self._trade_counter = 0
        self._lock = threading.RLock()
        
        self.on_trade_opened: Optional[Callable] = None
        self.on_trade_closed: Optional[Callable] = None
        self.on_session_complete: Optional[Callable] = None
        
        self._last_tick_price: float = 0.0
        self._tick_history: List[float] = []
        
        self._simulated_win_rate = 0.50
        self._strategy_signals: List[Dict] = []
        
    def set_simulated_win_rate(self, win_rate: float):
        """Set simulated win rate for paper trading (0.0 - 1.0)"""
        self._simulated_win_rate = max(0.0, min(1.0, win_rate))
        logger.info(f"Paper trading simulated win rate set to {self._simulated_win_rate:.1%}")
    
    def start_session(self, balance: Optional[float] = None):
        """Start a paper trading session"""
        if balance:
            self.initial_balance = balance
            self.balance = balance
        
        self.is_running = True
        self.session_trades = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_profit = 0.0
        self.trades = []
        self.active_trade = None
        self.equity_curve = [self.balance]
        self.peak_balance = self.balance
        self.max_drawdown = 0.0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.max_consecutive_wins = 0
        self.max_consecutive_losses = 0
        self._tick_history = []
        
        logger.info(f"Paper trading session started | Balance: ${self.balance:.2f}")
        return True
    
    def stop_session(self) -> BacktestResult:
        """Stop session and return results"""
        self.is_running = False
        
        result = self._generate_result()
        
        if self.on_session_complete:
            self.on_session_complete({
                "trades": self.session_trades,
                "wins": self.session_wins,
                "losses": self.session_losses,
                "profit": self.session_profit,
                "win_rate": self._get_win_rate(),
                "final_balance": self.balance
            })
        
        logger.info(
            f"Paper trading session stopped | "
            f"Trades: {self.session_trades} | "
            f"Win Rate: {self._get_win_rate():.1f}% | "
            f"Profit: ${self.session_profit:+.2f}"
        )
        
        return result
    
    def add_tick(self, price: float):
        """Add tick data for simulation"""
        self._last_tick_price = price
        self._tick_history.append(price)
        if len(self._tick_history) > 1000:
            self._tick_history = self._tick_history[-500:]
    
    def execute_trade(
        self,
        symbol: str,
        contract_type: str,
        stake: float,
        duration: int = 5,
        duration_unit: str = "t",
        entry_price: Optional[float] = None
    ) -> Optional[PaperTrade]:
        """
        Execute a simulated trade
        
        Returns the PaperTrade object if successful
        """
        with self._lock:
            if stake > self.balance:
                logger.warning(f"Insufficient balance for trade: ${stake} > ${self.balance}")
                return None
            
            if self.active_trade:
                logger.warning("Trade already in progress")
                return None
            
            self._trade_counter += 1
            trade_id = f"PAPER_{self._trade_counter}_{int(time.time())}"
            
            current_price = entry_price or self._last_tick_price or 1000.0
            
            trade = PaperTrade(
                trade_id=trade_id,
                symbol=symbol,
                contract_type=contract_type,
                stake=stake,
                entry_price=current_price,
                entry_time=datetime.now(),
                duration=duration,
                duration_unit=duration_unit
            )
            
            self.balance -= stake
            self.active_trade = trade
            
            if self.on_trade_opened:
                self.on_trade_opened({
                    "contract_id": trade_id,
                    "stake": stake,
                    "contract_type": contract_type,
                    "symbol": symbol,
                    "entry_price": current_price
                })
            
            logger.info(
                f"Paper trade opened | ID: {trade_id} | "
                f"{contract_type} on {symbol} | Stake: ${stake:.2f}"
            )
            
            self._schedule_trade_resolution(trade)
            
            return trade
    
    def _schedule_trade_resolution(self, trade: PaperTrade):
        """Schedule trade to be resolved after duration"""
        if trade.duration_unit == "t":
            delay = trade.duration * 2
        elif trade.duration_unit == "s":
            delay = trade.duration
        elif trade.duration_unit == "m":
            delay = trade.duration * 60
        else:
            delay = 5
        
        delay = min(delay, 30)
        
        def resolve():
            time.sleep(delay)
            self._resolve_trade(trade)
        
        thread = threading.Thread(target=resolve, daemon=True)
        thread.start()
    
    def _resolve_trade(self, trade: PaperTrade):
        """Resolve a paper trade (simulate outcome)"""
        with self._lock:
            if trade.is_closed:
                return
            
            is_win = random.random() < self._simulated_win_rate
            
            if self._tick_history:
                price_change = random.uniform(-0.001, 0.001) * trade.entry_price
                exit_price = trade.entry_price + price_change
            else:
                exit_price = trade.entry_price * (1 + random.uniform(-0.001, 0.001))
            
            trade.exit_price = exit_price
            trade.exit_time = datetime.now()
            trade.is_closed = True
            trade.is_win = is_win
            
            if is_win:
                trade.payout = trade.stake * (1 + self.payout_percent / 100)
                trade.profit = trade.payout - trade.stake
                self.balance += trade.payout
                self.session_wins += 1
                self.consecutive_wins += 1
                self.consecutive_losses = 0
                self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)
            else:
                trade.payout = 0
                trade.profit = -trade.stake
                self.session_losses += 1
                self.consecutive_losses += 1
                self.consecutive_wins = 0
                self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)
            
            self.session_trades += 1
            self.session_profit += trade.profit
            self.equity_curve.append(self.balance)
            self.trades.append(trade)
            
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance
            else:
                drawdown = (self.peak_balance - self.balance) / self.peak_balance * 100
                self.max_drawdown = max(self.max_drawdown, drawdown)
            
            self.active_trade = None
            
            if self.on_trade_closed:
                self.on_trade_closed({
                    "contract_id": trade.trade_id,
                    "profit": trade.profit,
                    "balance": self.balance,
                    "trades": self.session_trades,
                    "win_rate": self._get_win_rate(),
                    "is_win": is_win
                })
            
            result = "WIN" if is_win else "LOSS"
            logger.info(
                f"Paper trade {result} | ID: {trade.trade_id} | "
                f"Profit: ${trade.profit:+.2f} | Balance: ${self.balance:.2f}"
            )
    
    def resolve_trade_sync(self, trade: PaperTrade, is_win: bool, exit_price: Optional[float] = None):
        """
        Resolve a paper trade synchronously - used for backtesting
        Does not use threading, updates all stats immediately
        """
        with self._lock:
            if trade.is_closed:
                return
            
            trade.exit_price = exit_price or trade.entry_price
            trade.exit_time = datetime.now()
            trade.is_closed = True
            trade.is_win = is_win
            
            if is_win:
                trade.payout = trade.stake * (1 + self.payout_percent / 100)
                trade.profit = trade.payout - trade.stake
                self.balance += trade.payout
                self.session_wins += 1
                self.consecutive_wins += 1
                self.consecutive_losses = 0
                self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)
            else:
                trade.payout = 0
                trade.profit = -trade.stake
                self.session_losses += 1
                self.consecutive_losses += 1
                self.consecutive_wins = 0
                self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)
            
            self.session_trades += 1
            self.session_profit += trade.profit
            self.equity_curve.append(self.balance)
            self.trades.append(trade)
            
            if self.balance > self.peak_balance:
                self.peak_balance = self.balance
            else:
                drawdown = (self.peak_balance - self.balance) / self.peak_balance * 100
                self.max_drawdown = max(self.max_drawdown, drawdown)
            
            self.active_trade = None
    
    def _get_win_rate(self) -> float:
        if self.session_trades == 0:
            return 0.0
        return (self.session_wins / self.session_trades) * 100
    
    def _generate_result(self) -> BacktestResult:
        """Generate backtest result from session data"""
        total_wins_profit = sum(t.profit for t in self.trades if t.is_win)
        total_losses = sum(abs(t.profit) for t in self.trades if not t.is_win)
        
        profit_factor = total_wins_profit / total_losses if total_losses > 0 else 0.0
        
        avg_profit = self.session_profit / self.session_trades if self.session_trades > 0 else 0.0
        
        returns = []
        for i in range(1, len(self.equity_curve)):
            ret = (self.equity_curve[i] - self.equity_curve[i-1]) / self.equity_curve[i-1]
            returns.append(ret)
        
        if returns:
            import statistics
            try:
                mean_return = statistics.mean(returns)
                std_return = statistics.stdev(returns) if len(returns) > 1 else 1
                sharpe_ratio = (mean_return / std_return) * (252 ** 0.5) if std_return > 0 else 0
            except Exception:
                sharpe_ratio = 0.0
        else:
            sharpe_ratio = 0.0
        
        return BacktestResult(
            total_trades=self.session_trades,
            wins=self.session_wins,
            losses=self.session_losses,
            win_rate=self._get_win_rate(),
            total_profit=self.session_profit,
            max_drawdown=self.max_drawdown,
            max_consecutive_wins=self.max_consecutive_wins,
            max_consecutive_losses=self.max_consecutive_losses,
            avg_profit_per_trade=avg_profit,
            sharpe_ratio=sharpe_ratio,
            profit_factor=profit_factor,
            trades=self.trades.copy(),
            equity_curve=self.equity_curve.copy(),
            start_balance=self.initial_balance,
            end_balance=self.balance,
            duration_seconds=0.0
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get current paper trading status"""
        return {
            "mode": self.mode.value,
            "is_running": self.is_running,
            "balance": self.balance,
            "initial_balance": self.initial_balance,
            "session_trades": self.session_trades,
            "session_wins": self.session_wins,
            "session_losses": self.session_losses,
            "session_profit": self.session_profit,
            "win_rate": self._get_win_rate(),
            "max_drawdown": self.max_drawdown,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "has_active_trade": self.active_trade is not None
        }
    
    def get_trade_history(self, limit: int = 50) -> List[Dict]:
        """Get recent trade history"""
        recent_trades = self.trades[-limit:] if limit > 0 else self.trades
        return [
            {
                "trade_id": t.trade_id,
                "symbol": t.symbol,
                "contract_type": t.contract_type,
                "stake": t.stake,
                "profit": t.profit,
                "is_win": t.is_win,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat() if t.exit_time else None
            }
            for t in reversed(recent_trades)
        ]
    
    def get_equity_curve(self) -> List[float]:
        """Get equity curve data"""
        return self.equity_curve.copy()


class BacktestEngine:
    """
    Backtest Engine - Run strategy on historical data
    
    Features:
    - Load historical tick data
    - Run strategy signals through simulation
    - Generate comprehensive backtest reports
    """
    
    def __init__(self, initial_balance: float = 10000.0, payout_percent: float = 85.0):
        self.initial_balance = initial_balance
        self.payout_percent = payout_percent
        self.paper_manager = PaperTradingManager(initial_balance, payout_percent)
        self.paper_manager.mode = PaperTradingMode.BACKTEST
    
    def run_backtest(
        self,
        tick_data: List[float],
        signals: List[Dict],
        stake: float = 1.0
    ) -> BacktestResult:
        """
        Run backtest with provided tick data and signals
        
        Args:
            tick_data: List of price ticks
            signals: List of signal dicts with {index, direction, strength}
            stake: Base stake amount
            
        Returns:
            BacktestResult with all statistics
        """
        start_time = time.time()
        
        self.paper_manager = PaperTradingManager(self.initial_balance, self.payout_percent)
        self.paper_manager.mode = PaperTradingMode.BACKTEST
        self.paper_manager.start_session()
        
        look_ahead = 5
        
        for i, price in enumerate(tick_data):
            self.paper_manager.add_tick(price)
            
            matching_signals = [s for s in signals if s.get("index") == i]
            for signal in matching_signals:
                direction = signal.get("direction", "CALL")
                strength = signal.get("strength", 0.5)
                
                actual_stake = stake * (1 + strength * 0.5)
                
                trade = self._create_backtest_trade(
                    symbol="BACKTEST",
                    contract_type=direction,
                    stake=actual_stake,
                    entry_price=price
                )
                
                if trade and actual_stake <= self.paper_manager.balance:
                    self.paper_manager.balance -= actual_stake
                    
                    is_win = self._evaluate_signal(tick_data, i, direction, look_ahead)
                    exit_price = tick_data[min(i + look_ahead, len(tick_data) - 1)]
                    
                    self.paper_manager.resolve_trade_sync(trade, is_win, exit_price)
        
        result = self.paper_manager.stop_session()
        result.duration_seconds = time.time() - start_time
        
        return result
    
    def _create_backtest_trade(
        self,
        symbol: str,
        contract_type: str,
        stake: float,
        entry_price: float
    ) -> Optional[PaperTrade]:
        """Create a trade object for backtesting without async scheduling"""
        self.paper_manager._trade_counter += 1
        trade_id = f"BT_{self.paper_manager._trade_counter}_{int(time.time())}"
        
        return PaperTrade(
            trade_id=trade_id,
            symbol=symbol,
            contract_type=contract_type,
            stake=stake,
            entry_price=entry_price,
            entry_time=datetime.now(),
            duration=5,
            duration_unit="t"
        )
    
    def _evaluate_signal(
        self,
        tick_data: List[float],
        signal_index: int,
        direction: str,
        look_ahead: int = 5
    ) -> bool:
        """Evaluate if signal would have been profitable"""
        if signal_index + look_ahead >= len(tick_data):
            return random.random() < 0.5
        
        entry_price = tick_data[signal_index]
        exit_price = tick_data[signal_index + look_ahead]
        
        if direction.upper() in ["CALL", "RISE", "HIGHER", "DIGITOVER"]:
            return exit_price > entry_price
        elif direction.upper() in ["PUT", "FALL", "LOWER", "DIGITUNDER"]:
            return exit_price < entry_price
        else:
            return random.random() < 0.5
