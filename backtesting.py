"""
Backtesting Engine - Historical data testing for all strategies
Complete backtesting system with performance analytics
"""

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class BacktestMode(Enum):
    WALK_FORWARD = "WALK_FORWARD"
    MONTE_CARLO = "MONTE_CARLO"
    STANDARD = "STANDARD"


@dataclass
class BacktestTrade:
    entry_time: float
    exit_time: float
    direction: str
    entry_price: float
    exit_price: float
    stake: float
    profit: float
    is_win: bool
    strategy: str
    symbol: str
    confidence: float
    indicators: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    start_time: float
    end_time: float
    initial_balance: float
    final_balance: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_trade_duration: float
    total_profit: float
    total_loss: float
    expectancy: float
    recovery_factor: float
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    monthly_returns: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['trades'] = [asdict(t) for t in self.trades]
        return result


class HistoricalDataLoader:
    """Load and manage historical tick data"""
    
    CACHE_DIR = "data/historical"
    
    def __init__(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        self._cache: Dict[str, List[Dict]] = {}
    
    def load_ticks(self, symbol: str, start_date: datetime, end_date: datetime) -> List[Dict]:
        """Load historical ticks for a symbol"""
        cache_key = f"{symbol}_{start_date.date()}_{end_date.date()}"
        
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        cache_file = os.path.join(self.CACHE_DIR, f"{cache_key}.json")
        if os.path.exists(cache_file):
            with open(cache_file, 'r') as f:
                data = json.load(f)
                self._cache[cache_key] = data
                return data
        
        return []
    
    def save_ticks(self, symbol: str, start_date: datetime, end_date: datetime, ticks: List[Dict]):
        """Save historical ticks to cache"""
        cache_key = f"{symbol}_{start_date.date()}_{end_date.date()}"
        cache_file = os.path.join(self.CACHE_DIR, f"{cache_key}.json")
        
        with open(cache_file, 'w') as f:
            json.dump(ticks, f)
        
        self._cache[cache_key] = ticks
    
    def generate_synthetic_ticks(self, symbol: str, count: int = 10000, 
                                   base_price: float = 100.0, 
                                   volatility: float = 0.001) -> List[Dict]:
        """Generate synthetic tick data for testing"""
        import random
        
        ticks = []
        price = base_price
        timestamp = time.time() - (count * 2)
        
        for i in range(count):
            change = random.gauss(0, volatility * price)
            price = max(0.01, price + change)
            
            tick = {
                "symbol": symbol,
                "quote": round(price, 5),
                "epoch": int(timestamp),
                "pip_size": 5
            }
            ticks.append(tick)
            timestamp += random.uniform(1.5, 2.5)
        
        return ticks


class BacktestEngine:
    """
    Complete Backtesting Engine
    
    Features:
    - Historical data replay
    - Strategy performance analysis
    - Walk-forward optimization
    - Monte Carlo simulation
    - Detailed metrics and reporting
    """
    
    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.data_loader = HistoricalDataLoader()
        
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Dict] = []
        self.peak_balance = initial_balance
        self.max_drawdown = 0.0
        
        self._current_position: Optional[Dict] = None
    
    def run_backtest(
        self,
        strategy,
        symbol: str,
        ticks: List[Dict],
        stake: float = 1.0,
        payout_percent: float = 85.0
    ) -> BacktestResult:
        """
        Run backtest on historical data
        
        Args:
            strategy: Strategy instance with add_tick method
            symbol: Symbol being traded
            ticks: Historical tick data
            stake: Base stake amount
            payout_percent: Expected payout percentage
        """
        self.balance = self.initial_balance
        self.peak_balance = self.initial_balance
        self.max_drawdown = 0.0
        self.trades = []
        self.equity_curve = []
        
        strategy_name = type(strategy).__name__
        logger.info(f"Starting backtest: {strategy_name} on {symbol} with {len(ticks)} ticks")
        
        start_time = ticks[0]['epoch'] if ticks else time.time()
        
        for i, tick in enumerate(ticks):
            signal = None
            
            if hasattr(strategy, 'add_tick'):
                if hasattr(strategy, 'symbol_data'):
                    signal = strategy.add_tick(symbol, tick)
                else:
                    signal = strategy.add_tick(tick)
            
            if signal and hasattr(signal, 'direction') and signal.direction in ['BUY', 'SELL', 'CALL', 'PUT']:
                trade = self._simulate_trade(
                    tick=tick,
                    signal=signal,
                    stake=stake,
                    payout_percent=payout_percent,
                    strategy_name=strategy_name,
                    symbol=symbol,
                    future_ticks=ticks[i+1:i+6] if i+1 < len(ticks) else []
                )
                
                if trade:
                    self.trades.append(trade)
                    
                    self.equity_curve.append({
                        "time": tick['epoch'],
                        "balance": self.balance,
                        "drawdown": self._calculate_current_drawdown()
                    })
                    
                    self.peak_balance = max(self.peak_balance, self.balance)
                    current_dd = self._calculate_current_drawdown()
                    self.max_drawdown = max(self.max_drawdown, current_dd)
        
        end_time = ticks[-1]['epoch'] if ticks else time.time()
        
        return self._generate_result(strategy_name, symbol, start_time, end_time)
    
    def _simulate_trade(
        self,
        tick: Dict,
        signal,
        stake: float,
        payout_percent: float,
        strategy_name: str,
        symbol: str,
        future_ticks: List[Dict]
    ) -> Optional[BacktestTrade]:
        """Simulate a trade based on signal and future price movement"""
        if not future_ticks:
            return None
        
        entry_price = tick['quote']
        exit_tick = future_ticks[-1] if future_ticks else tick
        exit_price = exit_tick['quote']
        
        direction = getattr(signal, 'direction', 'BUY')
        if direction in ['CALL', 'BUY']:
            is_win = exit_price > entry_price
        elif direction in ['PUT', 'SELL']:
            is_win = exit_price < entry_price
        else:
            price_direction = 1 if exit_price > entry_price else -1
            confidence = getattr(signal, 'confidence', 0.5)
            import random
            is_win = random.random() < confidence
        
        if is_win:
            profit = stake * (payout_percent / 100)
        else:
            profit = -stake
        
        self.balance += profit
        
        trade = BacktestTrade(
            entry_time=tick['epoch'],
            exit_time=exit_tick['epoch'],
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            stake=stake,
            profit=profit,
            is_win=is_win,
            strategy=strategy_name,
            symbol=symbol,
            confidence=getattr(signal, 'confidence', 0.5),
            indicators=getattr(signal, 'indicators', {}) if hasattr(signal, 'indicators') else {}
        )
        
        return trade
    
    def _calculate_current_drawdown(self) -> float:
        """Calculate current drawdown percentage"""
        if self.peak_balance <= 0:
            return 0.0
        return (self.peak_balance - self.balance) / self.peak_balance
    
    def _generate_result(self, strategy: str, symbol: str, start_time: float, end_time: float) -> BacktestResult:
        """Generate comprehensive backtest result"""
        wins = [t for t in self.trades if t.is_win]
        losses = [t for t in self.trades if not t.is_win]
        
        total_wins = len(wins)
        total_losses = len(losses)
        total_trades = len(self.trades)
        
        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        
        total_profit = sum(t.profit for t in wins)
        total_loss = abs(sum(t.profit for t in losses))
        
        profit_factor = (total_profit / total_loss) if total_loss > 0 else float('inf')
        
        avg_win = (total_profit / total_wins) if total_wins > 0 else 0
        avg_loss = (total_loss / total_losses) if total_losses > 0 else 0
        
        largest_win = max([t.profit for t in wins], default=0)
        largest_loss = abs(min([t.profit for t in losses], default=0))
        
        avg_duration = 0
        if self.trades:
            durations = [t.exit_time - t.entry_time for t in self.trades]
            avg_duration = sum(durations) / len(durations)
        
        expectancy = 0
        if total_trades > 0:
            expectancy = (win_rate/100 * avg_win) - ((1 - win_rate/100) * avg_loss)
        
        sharpe = self._calculate_sharpe_ratio()
        sortino = self._calculate_sortino_ratio()
        
        recovery_factor = 0
        if self.max_drawdown > 0:
            net_profit = self.balance - self.initial_balance
            recovery_factor = net_profit / (self.max_drawdown * self.initial_balance)
        
        monthly_returns = self._calculate_monthly_returns()
        
        return BacktestResult(
            strategy=strategy,
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            initial_balance=self.initial_balance,
            final_balance=self.balance,
            total_trades=total_trades,
            wins=total_wins,
            losses=total_losses,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=self.max_drawdown * self.initial_balance,
            max_drawdown_pct=self.max_drawdown * 100,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            avg_trade_duration=avg_duration,
            total_profit=total_profit,
            total_loss=total_loss,
            expectancy=expectancy,
            recovery_factor=recovery_factor,
            trades=self.trades,
            equity_curve=self.equity_curve,
            monthly_returns=monthly_returns
        )
    
    def _calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe Ratio"""
        if len(self.trades) < 2:
            return 0.0
        
        returns = [t.profit / t.stake for t in self.trades]
        
        import statistics
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 1
        
        if std_return == 0:
            return 0.0
        
        daily_risk_free = risk_free_rate / 252
        sharpe = (mean_return - daily_risk_free) / std_return
        
        return sharpe
    
    def _calculate_sortino_ratio(self, risk_free_rate: float = 0.02) -> float:
        """Calculate Sortino Ratio (uses only downside deviation)"""
        if len(self.trades) < 2:
            return 0.0
        
        returns = [t.profit / t.stake for t in self.trades]
        negative_returns = [r for r in returns if r < 0]
        
        if not negative_returns:
            return float('inf')
        
        import statistics
        mean_return = statistics.mean(returns)
        downside_std = statistics.stdev(negative_returns) if len(negative_returns) > 1 else 1
        
        if downside_std == 0:
            return 0.0
        
        daily_risk_free = risk_free_rate / 252
        sortino = (mean_return - daily_risk_free) / downside_std
        
        return sortino
    
    def _calculate_monthly_returns(self) -> Dict[str, float]:
        """Calculate monthly returns"""
        monthly = {}
        
        for trade in self.trades:
            month_key = datetime.fromtimestamp(trade.entry_time).strftime("%Y-%m")
            if month_key not in monthly:
                monthly[month_key] = 0
            monthly[month_key] += trade.profit
        
        return monthly
    
    def run_walk_forward(
        self,
        strategy_class,
        symbol: str,
        ticks: List[Dict],
        in_sample_pct: float = 0.7,
        num_periods: int = 5,
        **strategy_kwargs
    ) -> List[BacktestResult]:
        """
        Run walk-forward optimization
        
        Splits data into in-sample (training) and out-of-sample (testing) periods
        """
        results = []
        period_size = len(ticks) // num_periods
        
        for i in range(num_periods - 1):
            in_sample_end = int((i + 1) * period_size * in_sample_pct) + i * period_size
            out_sample_start = in_sample_end
            out_sample_end = (i + 2) * period_size
            
            out_sample_ticks = ticks[out_sample_start:out_sample_end]
            
            if out_sample_ticks:
                strategy = strategy_class(**strategy_kwargs) if strategy_kwargs else strategy_class()
                result = self.run_backtest(strategy, symbol, out_sample_ticks)
                result.strategy = f"{result.strategy}_Period{i+1}"
                results.append(result)
        
        return results
    
    def run_monte_carlo(
        self,
        strategy,
        symbol: str,
        ticks: List[Dict],
        num_simulations: int = 100,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Run Monte Carlo simulation by shuffling trade order
        """
        base_result = self.run_backtest(strategy, symbol, ticks, **kwargs)
        
        if not base_result.trades:
            return {"base_result": base_result, "simulations": []}
        
        import random
        
        simulation_results = []
        
        for _ in range(num_simulations):
            shuffled_trades = base_result.trades.copy()
            random.shuffle(shuffled_trades)
            
            sim_balance = self.initial_balance
            sim_peak = self.initial_balance
            sim_max_dd = 0.0
            
            for trade in shuffled_trades:
                sim_balance += trade.profit
                sim_peak = max(sim_peak, sim_balance)
                current_dd = (sim_peak - sim_balance) / sim_peak if sim_peak > 0 else 0
                sim_max_dd = max(sim_max_dd, current_dd)
            
            simulation_results.append({
                "final_balance": sim_balance,
                "max_drawdown_pct": sim_max_dd * 100,
                "total_return": (sim_balance - self.initial_balance) / self.initial_balance * 100
            })
        
        final_balances = [s["final_balance"] for s in simulation_results]
        max_drawdowns = [s["max_drawdown_pct"] for s in simulation_results]
        
        return {
            "base_result": base_result,
            "simulations": simulation_results,
            "statistics": {
                "mean_final_balance": sum(final_balances) / len(final_balances),
                "min_final_balance": min(final_balances),
                "max_final_balance": max(final_balances),
                "mean_max_drawdown": sum(max_drawdowns) / len(max_drawdowns),
                "worst_drawdown": max(max_drawdowns),
                "probability_profit": len([b for b in final_balances if b > self.initial_balance]) / len(final_balances) * 100
            }
        }


class StrategyOptimizer:
    """Optimize strategy parameters using backtesting"""
    
    def __init__(self, backtest_engine: BacktestEngine):
        self.engine = backtest_engine
    
    def grid_search(
        self,
        strategy_class,
        symbol: str,
        ticks: List[Dict],
        param_grid: Dict[str, List[Any]],
        metric: str = "profit_factor"
    ) -> Tuple[Dict[str, Any], BacktestResult]:
        """
        Grid search for optimal parameters
        
        Args:
            strategy_class: Strategy class to optimize
            symbol: Symbol to test
            ticks: Historical tick data
            param_grid: Dict of parameter names to lists of values
            metric: Metric to optimize (profit_factor, sharpe_ratio, win_rate, etc.)
        """
        import itertools
        
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        
        best_params = None
        best_result = None
        best_metric_value = float('-inf')
        
        for values in itertools.product(*param_values):
            params = dict(zip(param_names, values))
            
            try:
                strategy = strategy_class(**params)
                result = self.engine.run_backtest(strategy, symbol, ticks)
                
                metric_value = getattr(result, metric, 0)
                
                if metric_value > best_metric_value:
                    best_metric_value = metric_value
                    best_params = params
                    best_result = result
                    
            except Exception as e:
                logger.warning(f"Failed to test params {params}: {e}")
                continue
        
        return best_params, best_result


def save_backtest_report(result: BacktestResult, filename: str = None) -> str:
    """Save backtest result to JSON file"""
    os.makedirs("logs/backtests", exist_ok=True)
    
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"logs/backtests/backtest_{result.strategy}_{result.symbol}_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    
    logger.info(f"Backtest report saved to {filename}")
    return filename


def generate_backtest_summary(result: BacktestResult) -> str:
    """Generate human-readable backtest summary"""
    net_profit = result.final_balance - result.initial_balance
    roi = (net_profit / result.initial_balance) * 100
    
    summary = f"""
================================================================================
                        BACKTEST REPORT: {result.strategy}
================================================================================

Symbol: {result.symbol}
Period: {datetime.fromtimestamp(result.start_time)} to {datetime.fromtimestamp(result.end_time)}

PERFORMANCE METRICS
-------------------
Initial Balance:     ${result.initial_balance:,.2f}
Final Balance:       ${result.final_balance:,.2f}
Net Profit/Loss:     ${net_profit:+,.2f} ({roi:+.2f}%)

Total Trades:        {result.total_trades}
Winning Trades:      {result.wins} ({result.win_rate:.1f}%)
Losing Trades:       {result.losses}

RISK METRICS
------------
Max Drawdown:        ${result.max_drawdown:,.2f} ({result.max_drawdown_pct:.2f}%)
Profit Factor:       {result.profit_factor:.2f}
Sharpe Ratio:        {result.sharpe_ratio:.2f}
Sortino Ratio:       {result.sortino_ratio:.2f}
Recovery Factor:     {result.recovery_factor:.2f}

TRADE STATISTICS
----------------
Average Win:         ${result.avg_win:,.2f}
Average Loss:        ${result.avg_loss:,.2f}
Largest Win:         ${result.largest_win:,.2f}
Largest Loss:        ${result.largest_loss:,.2f}
Expectancy:          ${result.expectancy:,.2f}
Avg Trade Duration:  {result.avg_trade_duration:.1f}s

================================================================================
"""
    return summary
