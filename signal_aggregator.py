"""
Signal Aggregator - Ensemble approach for combining multiple strategy signals
Provides weighted voting, consensus, and meta-learning signal combination
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import threading

logger = logging.getLogger(__name__)


class AggregationMethod(Enum):
    WEIGHTED_VOTE = "WEIGHTED_VOTE"
    CONSENSUS = "CONSENSUS"
    BEST_PERFORMER = "BEST_PERFORMER"
    META_LEARNER = "META_LEARNER"
    UNANIMOUS = "UNANIMOUS"


class SignalDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"
    CALL = "CALL"
    PUT = "PUT"
    HOLD = "HOLD"


@dataclass
class StrategySignal:
    strategy_name: str
    direction: str
    confidence: float
    timestamp: float
    indicators: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AggregatedSignal:
    direction: str
    confidence: float
    consensus_score: float
    contributing_strategies: List[str]
    strategy_signals: List[StrategySignal]
    aggregation_method: AggregationMethod
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_actionable(self) -> bool:
        return self.direction not in ["HOLD", "NEUTRAL"] and self.confidence >= 0.5


@dataclass
class StrategyPerformance:
    strategy_name: str
    total_signals: int = 0
    correct_signals: int = 0
    incorrect_signals: int = 0
    total_profit: float = 0.0
    win_rate: float = 0.0
    avg_confidence: float = 0.0
    weight: float = 1.0
    last_updated: float = 0.0
    
    def update_weight(self):
        """Update strategy weight based on performance"""
        if self.total_signals < 10:
            self.weight = 1.0
            return
        
        self.win_rate = self.correct_signals / self.total_signals if self.total_signals > 0 else 0
        
        profit_factor = 1.0 + (self.total_profit / 100) if self.total_profit > 0 else max(0.5, 1.0 + self.total_profit / 100)
        
        self.weight = self.win_rate * profit_factor
        self.weight = max(0.1, min(2.0, self.weight))


class SignalAggregator:
    """
    Signal Aggregation Engine
    
    Combines signals from multiple strategies using various methods:
    - Weighted voting based on historical performance
    - Consensus (majority voting)
    - Best performer selection
    - Meta-learning (adaptive weighting)
    
    Features:
    - Dynamic weight adjustment based on performance
    - Conflict resolution
    - Signal confidence boosting/penalization
    - Historical signal tracking
    """
    
    DEFAULT_WEIGHTS = {
        "TERMINAL": 1.2,
        "SNIPER": 1.5,
        "MULTI_INDICATOR": 1.0,
        "TICK_PICKER": 0.9,
        "DIGITPAD": 0.8,
        "LDP": 0.85,
        "AMT": 1.1,
        "TICK_ANALYZER": 0.9
    }
    
    MIN_CONFIDENCE_THRESHOLD = 0.50
    CONSENSUS_THRESHOLD = 0.60
    SIGNAL_EXPIRY_SECONDS = 30
    
    def __init__(
        self,
        method: AggregationMethod = AggregationMethod.WEIGHTED_VOTE,
        min_strategies: int = 2,
        adaptive_weights: bool = True
    ):
        self.method = method
        self.min_strategies = min_strategies
        self.adaptive_weights = adaptive_weights
        
        self._strategy_weights: Dict[str, float] = dict(self.DEFAULT_WEIGHTS)
        self._strategy_performance: Dict[str, StrategyPerformance] = {}
        
        self._pending_signals: Dict[str, StrategySignal] = {}
        self._signal_history: deque = deque(maxlen=1000)
        self._aggregated_history: deque = deque(maxlen=500)
        
        self._lock = threading.RLock()
        
        self._last_aggregation_time = 0
        self._min_aggregation_interval = 5.0
    
    def add_signal(self, signal: StrategySignal) -> Optional[AggregatedSignal]:
        """
        Add a signal from a strategy
        
        Returns aggregated signal if enough signals are collected
        """
        with self._lock:
            if signal.strategy_name not in self._strategy_performance:
                self._strategy_performance[signal.strategy_name] = StrategyPerformance(
                    strategy_name=signal.strategy_name
                )
            
            self._pending_signals[signal.strategy_name] = signal
            self._signal_history.append(signal)
            
            self._cleanup_expired_signals()
            
            if len(self._pending_signals) >= self.min_strategies:
                if time.time() - self._last_aggregation_time >= self._min_aggregation_interval:
                    return self._aggregate()
            
            return None
    
    def force_aggregate(self) -> Optional[AggregatedSignal]:
        """Force aggregation with available signals"""
        with self._lock:
            self._cleanup_expired_signals()
            if self._pending_signals:
                return self._aggregate()
            return None
    
    def _aggregate(self) -> Optional[AggregatedSignal]:
        """Perform signal aggregation based on configured method"""
        if not self._pending_signals:
            return None
        
        signals = list(self._pending_signals.values())
        
        if self.method == AggregationMethod.WEIGHTED_VOTE:
            result = self._weighted_vote(signals)
        elif self.method == AggregationMethod.CONSENSUS:
            result = self._consensus(signals)
        elif self.method == AggregationMethod.BEST_PERFORMER:
            result = self._best_performer(signals)
        elif self.method == AggregationMethod.META_LEARNER:
            result = self._meta_learner(signals)
        elif self.method == AggregationMethod.UNANIMOUS:
            result = self._unanimous(signals)
        else:
            result = self._weighted_vote(signals)
        
        if result:
            self._aggregated_history.append(result)
            self._last_aggregation_time = time.time()
            self._pending_signals.clear()
        
        return result
    
    def _weighted_vote(self, signals: List[StrategySignal]) -> Optional[AggregatedSignal]:
        """Aggregate using weighted voting"""
        direction_votes: Dict[str, float] = {}
        direction_confidences: Dict[str, List[float]] = {}
        direction_strategies: Dict[str, List[str]] = {}
        
        for signal in signals:
            direction = self._normalize_direction(signal.direction)
            if direction == "HOLD":
                continue
            
            weight = self._get_weight(signal.strategy_name)
            weighted_confidence = signal.confidence * weight
            
            if direction not in direction_votes:
                direction_votes[direction] = 0
                direction_confidences[direction] = []
                direction_strategies[direction] = []
            
            direction_votes[direction] += weighted_confidence
            direction_confidences[direction].append(signal.confidence)
            direction_strategies[direction].append(signal.strategy_name)
        
        if not direction_votes:
            return None
        
        winning_direction = max(direction_votes, key=direction_votes.get)
        
        total_vote = sum(direction_votes.values())
        consensus_score = direction_votes[winning_direction] / total_vote if total_vote > 0 else 0
        
        confidences = direction_confidences[winning_direction]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        
        final_confidence = avg_confidence * (0.5 + 0.5 * consensus_score)
        
        return AggregatedSignal(
            direction=winning_direction,
            confidence=final_confidence,
            consensus_score=consensus_score,
            contributing_strategies=direction_strategies[winning_direction],
            strategy_signals=signals,
            aggregation_method=AggregationMethod.WEIGHTED_VOTE,
            timestamp=time.time(),
            metadata={
                "direction_votes": direction_votes,
                "total_strategies": len(signals)
            }
        )
    
    def _consensus(self, signals: List[StrategySignal]) -> Optional[AggregatedSignal]:
        """Aggregate using majority consensus"""
        direction_counts: Dict[str, int] = {}
        direction_signals: Dict[str, List[StrategySignal]] = {}
        
        for signal in signals:
            direction = self._normalize_direction(signal.direction)
            if direction == "HOLD":
                continue
            
            if direction not in direction_counts:
                direction_counts[direction] = 0
                direction_signals[direction] = []
            
            direction_counts[direction] += 1
            direction_signals[direction].append(signal)
        
        if not direction_counts:
            return None
        
        winning_direction = max(direction_counts, key=direction_counts.get)
        
        consensus_score = direction_counts[winning_direction] / len(signals)
        
        if consensus_score < self.CONSENSUS_THRESHOLD:
            return None
        
        winning_signals = direction_signals[winning_direction]
        avg_confidence = sum(s.confidence for s in winning_signals) / len(winning_signals)
        
        return AggregatedSignal(
            direction=winning_direction,
            confidence=avg_confidence,
            consensus_score=consensus_score,
            contributing_strategies=[s.strategy_name for s in winning_signals],
            strategy_signals=signals,
            aggregation_method=AggregationMethod.CONSENSUS,
            timestamp=time.time(),
            metadata={
                "direction_counts": direction_counts,
                "required_consensus": self.CONSENSUS_THRESHOLD
            }
        )
    
    def _best_performer(self, signals: List[StrategySignal]) -> Optional[AggregatedSignal]:
        """Select signal from best performing strategy"""
        best_signal = None
        best_score = -1
        
        for signal in signals:
            direction = self._normalize_direction(signal.direction)
            if direction == "HOLD":
                continue
            
            perf = self._strategy_performance.get(signal.strategy_name)
            if perf and perf.total_signals >= 10:
                score = perf.win_rate * signal.confidence
            else:
                score = signal.confidence * self._get_weight(signal.strategy_name)
            
            if score > best_score:
                best_score = score
                best_signal = signal
        
        if not best_signal:
            return None
        
        return AggregatedSignal(
            direction=self._normalize_direction(best_signal.direction),
            confidence=best_signal.confidence,
            consensus_score=1.0,
            contributing_strategies=[best_signal.strategy_name],
            strategy_signals=[best_signal],
            aggregation_method=AggregationMethod.BEST_PERFORMER,
            timestamp=time.time(),
            metadata={
                "selected_strategy": best_signal.strategy_name,
                "selection_score": best_score
            }
        )
    
    def _meta_learner(self, signals: List[StrategySignal]) -> Optional[AggregatedSignal]:
        """Adaptive meta-learning approach"""
        if self.adaptive_weights:
            for strategy_name, perf in self._strategy_performance.items():
                perf.update_weight()
                self._strategy_weights[strategy_name] = perf.weight
        
        return self._weighted_vote(signals)
    
    def _unanimous(self, signals: List[StrategySignal]) -> Optional[AggregatedSignal]:
        """Require all strategies to agree"""
        directions = set()
        
        for signal in signals:
            direction = self._normalize_direction(signal.direction)
            if direction != "HOLD":
                directions.add(direction)
        
        if len(directions) != 1:
            return None
        
        unanimous_direction = directions.pop()
        avg_confidence = sum(s.confidence for s in signals) / len(signals)
        
        return AggregatedSignal(
            direction=unanimous_direction,
            confidence=avg_confidence * 1.2,
            consensus_score=1.0,
            contributing_strategies=[s.strategy_name for s in signals],
            strategy_signals=signals,
            aggregation_method=AggregationMethod.UNANIMOUS,
            timestamp=time.time(),
            metadata={
                "all_strategies_agreed": True
            }
        )
    
    def _normalize_direction(self, direction: str) -> str:
        """Normalize direction to standard format"""
        direction = direction.upper()
        
        if direction in ["BUY", "CALL", "LONG", "UP"]:
            return "BUY"
        elif direction in ["SELL", "PUT", "SHORT", "DOWN"]:
            return "SELL"
        else:
            return "HOLD"
    
    def _get_weight(self, strategy_name: str) -> float:
        """Get weight for a strategy"""
        return self._strategy_weights.get(strategy_name, 1.0)
    
    def _cleanup_expired_signals(self):
        """Remove expired signals"""
        now = time.time()
        expired = [
            name for name, signal in self._pending_signals.items()
            if now - signal.timestamp > self.SIGNAL_EXPIRY_SECONDS
        ]
        for name in expired:
            del self._pending_signals[name]
    
    def record_outcome(self, aggregated_signal: AggregatedSignal, is_win: bool, profit: float):
        """Record the outcome of an aggregated signal for learning"""
        with self._lock:
            for strategy_name in aggregated_signal.contributing_strategies:
                if strategy_name not in self._strategy_performance:
                    self._strategy_performance[strategy_name] = StrategyPerformance(
                        strategy_name=strategy_name
                    )
                
                perf = self._strategy_performance[strategy_name]
                perf.total_signals += 1
                perf.total_profit += profit
                perf.last_updated = time.time()
                
                if is_win:
                    perf.correct_signals += 1
                else:
                    perf.incorrect_signals += 1
                
                for signal in aggregated_signal.strategy_signals:
                    if signal.strategy_name == strategy_name:
                        if perf.avg_confidence == 0:
                            perf.avg_confidence = signal.confidence
                        else:
                            perf.avg_confidence = (perf.avg_confidence * 0.9) + (signal.confidence * 0.1)
                        break
                
                if self.adaptive_weights:
                    perf.update_weight()
                    self._strategy_weights[strategy_name] = perf.weight
    
    def get_strategy_rankings(self) -> List[Dict[str, Any]]:
        """Get strategies ranked by performance"""
        with self._lock:
            rankings = []
            for name, perf in self._strategy_performance.items():
                rankings.append({
                    "strategy": name,
                    "total_signals": perf.total_signals,
                    "win_rate": perf.win_rate,
                    "total_profit": perf.total_profit,
                    "weight": perf.weight,
                    "avg_confidence": perf.avg_confidence
                })
            
            rankings.sort(key=lambda x: (x["win_rate"], x["total_profit"]), reverse=True)
            return rankings
    
    def get_stats(self) -> Dict[str, Any]:
        """Get aggregator statistics"""
        with self._lock:
            return {
                "method": self.method.value,
                "min_strategies": self.min_strategies,
                "adaptive_weights": self.adaptive_weights,
                "pending_signals": len(self._pending_signals),
                "signal_history_size": len(self._signal_history),
                "aggregated_history_size": len(self._aggregated_history),
                "strategy_weights": dict(self._strategy_weights),
                "strategy_performance": {
                    name: {
                        "total_signals": perf.total_signals,
                        "win_rate": perf.win_rate,
                        "weight": perf.weight
                    }
                    for name, perf in self._strategy_performance.items()
                }
            }
    
    def set_method(self, method: AggregationMethod):
        """Change aggregation method"""
        with self._lock:
            self.method = method
            logger.info(f"Aggregation method changed to: {method.value}")
    
    def set_strategy_weight(self, strategy_name: str, weight: float):
        """Manually set a strategy weight"""
        with self._lock:
            self._strategy_weights[strategy_name] = max(0.1, min(3.0, weight))
    
    def reset(self):
        """Reset aggregator state"""
        with self._lock:
            self._pending_signals.clear()
            self._signal_history.clear()
            self._aggregated_history.clear()
            self._strategy_weights = dict(self.DEFAULT_WEIGHTS)
            self._strategy_performance.clear()
            self._last_aggregation_time = 0


signal_aggregator = SignalAggregator(
    method=AggregationMethod.WEIGHTED_VOTE,
    min_strategies=2,
    adaptive_weights=True
)
