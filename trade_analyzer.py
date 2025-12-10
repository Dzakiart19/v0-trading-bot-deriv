"""
Trade History Analyzer - Pattern detection and strategy recommendations
"""

import logging
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    CHOPPY = "CHOPPY"
    UNKNOWN = "UNKNOWN"


@dataclass
class TradeAnalysis:
    """Analysis result for trade patterns"""
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    consecutive_losses: int
    consecutive_wins: int
    losing_streak_detected: bool
    should_switch_strategy: bool
    recommended_action: str
    market_regime: MarketRegime
    strategy_performance: Dict[str, float]


class TradeHistoryAnalyzer:
    """
    Trade History Analyzer
    
    Features:
    - Pattern detection for losing streaks
    - Win rate tracking per strategy
    - Market regime detection (trending/ranging/choppy)
    - Strategy switch recommendations
    - Automatic pause on 3+ consecutive losses
    """
    
    # Thresholds
    MIN_TRADES_FOR_ANALYSIS = 5
    LOSING_STREAK_THRESHOLD = 3
    LOW_WIN_RATE_THRESHOLD = 0.40  # 40%
    SWITCH_STRATEGY_THRESHOLD = 0.35  # 35%
    
    def __init__(self):
        self.trade_history: deque = deque(maxlen=200)
        self.strategy_stats: Dict[str, Dict] = {}
        self.current_strategy: Optional[str] = None
        self.market_regime = MarketRegime.UNKNOWN
        
        # Consecutive tracking
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.last_result: Optional[bool] = None
        
        # Price history for regime detection
        self.price_history: deque = deque(maxlen=100)
    
    def record_trade(
        self, 
        strategy: str, 
        is_win: bool, 
        profit: float,
        entry_price: float = 0,
        exit_price: float = 0
    ):
        """Record a trade result"""
        trade = {
            "strategy": strategy,
            "is_win": is_win,
            "profit": profit,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "timestamp": time.time()
        }
        self.trade_history.append(trade)
        
        # Update strategy stats
        if strategy not in self.strategy_stats:
            self.strategy_stats[strategy] = {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "total_profit": 0,
                "last_trades": deque(maxlen=20)
            }
        
        stats = self.strategy_stats[strategy]
        stats["total"] += 1
        stats["total_profit"] += profit
        stats["last_trades"].append(is_win)
        
        if is_win:
            stats["wins"] += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            stats["losses"] += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
        
        self.last_result = is_win
        self.current_strategy = strategy
        
        logger.debug(
            f"Trade recorded: {strategy} {'WIN' if is_win else 'LOSS'} "
            f"profit={profit:.2f} consecutive_losses={self.consecutive_losses}"
        )
    
    def add_price_tick(self, price: float):
        """Add price tick for market regime analysis"""
        self.price_history.append({
            "price": price,
            "timestamp": time.time()
        })
        
        # Update market regime periodically
        if len(self.price_history) >= 50:
            self.market_regime = self._detect_market_regime()
    
    def analyze(self) -> TradeAnalysis:
        """Analyze trade history and return recommendations"""
        trades = list(self.trade_history)
        total = len(trades)
        
        if total < self.MIN_TRADES_FOR_ANALYSIS:
            return TradeAnalysis(
                total_trades=total,
                wins=sum(1 for t in trades if t["is_win"]),
                losses=sum(1 for t in trades if not t["is_win"]),
                win_rate=0,
                consecutive_losses=self.consecutive_losses,
                consecutive_wins=self.consecutive_wins,
                losing_streak_detected=False,
                should_switch_strategy=False,
                recommended_action="Collecting more data...",
                market_regime=self.market_regime,
                strategy_performance={}
            )
        
        wins = sum(1 for t in trades if t["is_win"])
        losses = total - wins
        win_rate = wins / total if total > 0 else 0
        
        # Check for losing streak
        losing_streak = self.consecutive_losses >= self.LOSING_STREAK_THRESHOLD
        
        # Check if should switch strategy
        current_stats = self._get_current_strategy_stats()
        should_switch = self._should_switch_strategy(current_stats)
        
        # Generate recommendation
        recommendation = self._generate_recommendation(
            win_rate, 
            losing_streak, 
            should_switch,
            current_stats
        )
        
        # Calculate strategy performance
        strategy_perf = self._calculate_strategy_performance()
        
        return TradeAnalysis(
            total_trades=total,
            wins=wins,
            losses=losses,
            win_rate=win_rate * 100,
            consecutive_losses=self.consecutive_losses,
            consecutive_wins=self.consecutive_wins,
            losing_streak_detected=losing_streak,
            should_switch_strategy=should_switch,
            recommended_action=recommendation,
            market_regime=self.market_regime,
            strategy_performance=strategy_perf
        )
    
    def _get_current_strategy_stats(self) -> Dict[str, Any]:
        """Get stats for current strategy"""
        if not self.current_strategy:
            return {}
        
        stats = self.strategy_stats.get(self.current_strategy, {})
        if not stats or stats.get("total", 0) == 0:
            return {}
        
        return {
            "strategy": self.current_strategy,
            "total": stats["total"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": stats["wins"] / stats["total"],
            "profit": stats["total_profit"],
            "recent_win_rate": self._calculate_recent_win_rate(stats)
        }
    
    def _calculate_recent_win_rate(self, stats: Dict) -> float:
        """Calculate win rate for last 10 trades"""
        recent = list(stats.get("last_trades", []))
        if not recent:
            return 0
        return sum(recent) / len(recent)
    
    def _should_switch_strategy(self, current_stats: Dict) -> bool:
        """Determine if strategy should be switched"""
        if not current_stats:
            return False
        
        # Check if current strategy is underperforming
        win_rate = current_stats.get("win_rate", 0)
        recent_win_rate = current_stats.get("recent_win_rate", 0)
        
        # Switch if both overall and recent performance is poor
        if win_rate < self.SWITCH_STRATEGY_THRESHOLD and recent_win_rate < self.LOW_WIN_RATE_THRESHOLD:
            return True
        
        # Switch if recent performance is very poor
        if recent_win_rate < 0.25 and current_stats.get("total", 0) >= 10:
            return True
        
        return False
    
    def _calculate_strategy_performance(self) -> Dict[str, float]:
        """Calculate performance score for each strategy"""
        performance = {}
        
        for strategy, stats in self.strategy_stats.items():
            if stats["total"] < 3:
                continue
            
            win_rate = stats["wins"] / stats["total"]
            profit_factor = stats["total_profit"] / max(1, stats["losses"])
            
            # Performance score: weighted win rate and profit
            score = (win_rate * 0.7) + (min(profit_factor / 10, 0.3))
            performance[strategy] = round(score * 100, 1)
        
        return performance
    
    def _detect_market_regime(self) -> MarketRegime:
        """Detect current market regime from price history"""
        prices = [p["price"] for p in list(self.price_history)]
        
        if len(prices) < 30:
            return MarketRegime.UNKNOWN
        
        # Calculate metrics
        returns = []
        for i in range(1, len(prices)):
            ret = (prices[i] - prices[i-1]) / prices[i-1]
            returns.append(ret)
        
        if not returns:
            return MarketRegime.UNKNOWN
        
        # Mean and std of returns
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
        std_ret = variance ** 0.5
        
        # Direction consistency
        positive_returns = sum(1 for r in returns if r > 0)
        direction_ratio = positive_returns / len(returns)
        
        # Classify regime
        if std_ret > 0.002:  # High volatility
            if abs(direction_ratio - 0.5) > 0.15:
                return MarketRegime.TRENDING
            else:
                return MarketRegime.CHOPPY
        else:  # Low volatility
            if abs(direction_ratio - 0.5) > 0.1:
                return MarketRegime.TRENDING
            else:
                return MarketRegime.RANGING
    
    def _generate_recommendation(
        self, 
        win_rate: float,
        losing_streak: bool,
        should_switch: bool,
        current_stats: Dict
    ) -> str:
        """Generate trading recommendation"""
        recommendations = []
        
        # Losing streak warning
        if losing_streak:
            recommendations.append(
                f"⚠️ PAUSE TRADING: {self.consecutive_losses} consecutive losses. "
                "Consider waiting for better conditions."
            )
        
        # Low win rate warning
        if win_rate < self.LOW_WIN_RATE_THRESHOLD:
            recommendations.append(
                f"📉 Win rate low ({win_rate*100:.1f}%). "
                "Review strategy parameters."
            )
        
        # Strategy switch recommendation
        if should_switch:
            best_strategy = self._get_best_performing_strategy()
            if best_strategy and best_strategy != self.current_strategy:
                recommendations.append(
                    f"💡 Consider switching to {best_strategy} "
                    "(higher recent performance)"
                )
        
        # Market regime advice
        if self.market_regime == MarketRegime.CHOPPY:
            recommendations.append(
                "🌊 Market is choppy. Reduce trade frequency."
            )
        elif self.market_regime == MarketRegime.RANGING:
            recommendations.append(
                "📊 Market is ranging. Digit/Range strategies may work better."
            )
        elif self.market_regime == MarketRegime.TRENDING:
            recommendations.append(
                "📈 Market is trending. Trend-following strategies preferred."
            )
        
        if not recommendations:
            if win_rate > 0.55:
                return "✅ Trading performance is good. Continue current strategy."
            else:
                return "📊 Performance is average. Monitor closely."
        
        return " | ".join(recommendations)
    
    def _get_best_performing_strategy(self) -> Optional[str]:
        """Get the best performing strategy based on recent trades"""
        best_strategy = None
        best_score = 0
        
        for strategy, stats in self.strategy_stats.items():
            if stats["total"] < 5:
                continue
            
            recent_win_rate = self._calculate_recent_win_rate(stats)
            if recent_win_rate > best_score:
                best_score = recent_win_rate
                best_strategy = strategy
        
        return best_strategy
    
    def should_pause(self) -> tuple:
        """
        Check if trading should be paused
        
        Returns:
            tuple: (should_pause: bool, reason: str)
        """
        if self.consecutive_losses >= self.LOSING_STREAK_THRESHOLD:
            return True, f"Losing streak: {self.consecutive_losses} consecutive losses"
        
        # Check recent performance
        recent_trades = list(self.trade_history)[-10:]
        if len(recent_trades) >= 10:
            recent_wins = sum(1 for t in recent_trades if t["is_win"])
            if recent_wins <= 2:  # 20% or less win rate in last 10
                return True, "Very poor recent performance (≤20% win rate)"
        
        return False, ""
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics"""
        trades = list(self.trade_history)
        total = len(trades)
        
        if total == 0:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "total_profit": 0,
                "consecutive_losses": 0,
                "consecutive_wins": 0,
                "market_regime": self.market_regime.value
            }
        
        wins = sum(1 for t in trades if t["is_win"])
        total_profit = sum(t["profit"] for t in trades)
        
        return {
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": (wins / total) * 100,
            "total_profit": total_profit,
            "consecutive_losses": self.consecutive_losses,
            "consecutive_wins": self.consecutive_wins,
            "market_regime": self.market_regime.value,
            "strategy_stats": {
                s: {
                    "total": d["total"],
                    "win_rate": (d["wins"] / d["total"] * 100) if d["total"] > 0 else 0
                }
                for s, d in self.strategy_stats.items()
            }
        }
    
    def reset(self):
        """Reset analyzer state"""
        self.trade_history.clear()
        self.strategy_stats.clear()
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.last_result = None
        self.price_history.clear()
        self.market_regime = MarketRegime.UNKNOWN
        logger.info("Trade analyzer reset")
