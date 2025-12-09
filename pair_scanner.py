"""
Pair Scanner - Multi-symbol parallel analysis for best trading opportunities
"""

import logging
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from collections import deque

from deriv_ws import DerivWebSocket
from strategy import MultiIndicatorStrategy
from symbols import get_short_term_symbols

logger = logging.getLogger(__name__)

@dataclass
class PairRecommendation:
    """Recommendation for a trading pair"""
    symbol: str
    direction: str
    score: float  # 0-100
    confidence: float
    confluence: float
    reasons: List[str]

class PairScanner:
    """
    Multi-Pair Scanner
    
    Parallel scanning of multiple symbols to find best trading opportunities.
    Each symbol has its own strategy instance for independent analysis.
    """
    
    MAX_TICKS_PER_SYMBOL = 200
    PRUNE_INTERVAL = 1000
    
    def __init__(self, ws: DerivWebSocket):
        self.ws = ws
        self.running = False
        
        # Per-symbol data
        self._strategies: Dict[str, MultiIndicatorStrategy] = {}
        self._tick_counts: Dict[str, int] = {}
        self._last_signals: Dict[str, Any] = {}
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Callbacks
        self.on_recommendation: Optional[Callable] = None
    
    def start_scanning(self, symbols: Optional[List[str]] = None):
        """Start scanning specified symbols or all short-term symbols"""
        if self.running:
            logger.warning("Scanner already running")
            return
        
        symbols = symbols or get_short_term_symbols()
        
        with self._lock:
            for symbol in symbols:
                # Initialize strategy for symbol
                self._strategies[symbol] = MultiIndicatorStrategy(symbol)
                self._tick_counts[symbol] = 0
                
                # Subscribe to ticks
                self.ws.subscribe_ticks(symbol, self._create_tick_handler(symbol))
            
            self.running = True
        
        logger.info(f"Pair scanner started for {len(symbols)} symbols")
    
    def stop_scanning(self):
        """Stop all scanning"""
        if not self.running:
            return
        
        with self._lock:
            # Unsubscribe from all symbols
            for symbol in list(self._strategies.keys()):
                self.ws.unsubscribe_ticks(symbol)
            
            self._strategies.clear()
            self._tick_counts.clear()
            self._last_signals.clear()
            self.running = False
        
        logger.info("Pair scanner stopped")
    
    def _create_tick_handler(self, symbol: str) -> Callable:
        """Create tick handler for specific symbol"""
        def handler(tick: Dict[str, Any]):
            self._on_tick(symbol, tick)
        return handler
    
    def _on_tick(self, symbol: str, tick: Dict[str, Any]):
        """Handle tick for a specific symbol"""
        if not self.running:
            return
        
        with self._lock:
            if symbol not in self._strategies:
                return
            
            strategy = self._strategies[symbol]
            signal = strategy.add_tick(tick)
            
            self._tick_counts[symbol] = self._tick_counts.get(symbol, 0) + 1
            
            if signal:
                self._last_signals[symbol] = signal
                
                # Calculate score
                score = self._calculate_score(signal)
                
                if self.on_recommendation and score >= 50:
                    rec = PairRecommendation(
                        symbol=symbol,
                        direction=signal.direction,
                        score=score,
                        confidence=signal.confidence,
                        confluence=signal.confluence,
                        reasons=[signal.reason]
                    )
                    self.on_recommendation(rec)
            
            # Periodic pruning
            total_ticks = sum(self._tick_counts.values())
            if total_ticks % self.PRUNE_INTERVAL == 0:
                self._prune_old_data()
    
    def _calculate_score(self, signal) -> float:
        """Calculate recommendation score from signal"""
        score = 50  # Base score for any signal
        
        # Confidence bonus (max 30)
        score += signal.confidence * 30
        
        # Confluence bonus (max 20)
        score += (signal.confluence / 100) * 20
        
        # ADX bonus from indicators
        indicators = signal.indicators
        adx = indicators.get("adx", 0)
        
        if adx >= 25:
            score += 15  # Strong trend
        elif adx >= 18:
            score += 10  # Moderate trend
        
        # Volatility penalty
        vol_pct = indicators.get("volatility_percentile", 50)
        if vol_pct > 85:
            score -= 10  # High volatility penalty
        
        return min(100, max(0, score))
    
    def _prune_old_data(self):
        """Prune old tick data from strategies"""
        # Strategies handle their own data pruning via deque maxlen
        logger.debug("Pair scanner data pruned")
    
    def get_recommendations(self, top_n: int = 3) -> List[PairRecommendation]:
        """Get top N pair recommendations"""
        with self._lock:
            recommendations = []
            
            for symbol, signal in self._last_signals.items():
                score = self._calculate_score(signal)
                
                rec = PairRecommendation(
                    symbol=symbol,
                    direction=signal.direction,
                    score=score,
                    confidence=signal.confidence,
                    confluence=signal.confluence,
                    reasons=[signal.reason]
                )
                recommendations.append(rec)
            
            # Sort by score descending
            recommendations.sort(key=lambda r: r.score, reverse=True)
            
            return recommendations[:top_n]
    
    def get_all_pair_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all scanned pairs"""
        with self._lock:
            status = {}
            
            for symbol, strategy in self._strategies.items():
                analysis = strategy.get_current_analysis()
                last_signal = self._last_signals.get(symbol)
                
                status[symbol] = {
                    "ticks": self._tick_counts.get(symbol, 0),
                    "analysis": analysis,
                    "last_signal": {
                        "direction": last_signal.direction if last_signal else None,
                        "confidence": last_signal.confidence if last_signal else None,
                        "time": last_signal.timestamp if last_signal else None
                    } if last_signal else None
                }
            
            return status
    
    def add_symbol(self, symbol: str):
        """Add a symbol to scan"""
        with self._lock:
            if symbol in self._strategies:
                return
            
            self._strategies[symbol] = MultiIndicatorStrategy(symbol)
            self._tick_counts[symbol] = 0
            self.ws.subscribe_ticks(symbol, self._create_tick_handler(symbol))
            
            logger.info(f"Added symbol to scanner: {symbol}")
    
    def remove_symbol(self, symbol: str):
        """Remove a symbol from scanning"""
        with self._lock:
            if symbol not in self._strategies:
                return
            
            self.ws.unsubscribe_ticks(symbol)
            del self._strategies[symbol]
            self._tick_counts.pop(symbol, None)
            self._last_signals.pop(symbol, None)
            
            logger.info(f"Removed symbol from scanner: {symbol}")
