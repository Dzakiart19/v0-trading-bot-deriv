"""
Tick Analyzer Strategy - Pattern detection based on consecutive ticks
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from collections import deque

logger = logging.getLogger(__name__)

@dataclass
class TickSignal:
    """Tick analyzer signal"""
    direction: str  # BUY or SELL
    signal_type: str  # reversal, continuation, breakout
    confidence: float
    reason: str
    pattern_data: Dict[str, Any]
    timestamp: float
    symbol: str

class TickAnalyzerStrategy:
    """
    Tick Analyzer Strategy
    
    Analyzes consecutive tick patterns for:
    - Reversal signals after extended streaks
    - Continuation signals with momentum
    - Breakout signals from consolidation
    - Support/Resistance detection
    """
    
    # Thresholds - LOWERED for more signals
    MIN_STREAK = 2  # Lowered from 3
    REVERSAL_STREAK = 4  # Lowered from 5
    SHORT_WINDOW = 5
    MEDIUM_WINDOW = 10
    LONG_WINDOW = 20
    MIN_TICKS = 20  # Added for consistency
    
    def __init__(self, symbol: str = "R_100"):
        self.symbol = symbol
        self.tick_history: deque = deque(maxlen=200)
        self.prices: deque = deque(maxlen=200)
        self.last_signal_time = 0
        self.signal_cooldown = 4  # Reduced from 8 seconds
    
    def add_tick(self, tick: Dict[str, Any]) -> Optional[TickSignal]:
        """Add tick and analyze for patterns"""
        quote = tick.get("quote", 0)
        if quote <= 0:
            return None
        
        self.tick_history.append(tick)
        self.prices.append(quote)
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_signal_time < self.signal_cooldown:
            return None
        
        # Need minimum data
        if len(self.prices) < self.MIN_TICKS:
            return None
        
        return self._analyze()
    
    def _analyze(self) -> Optional[TickSignal]:
        """Analyze tick patterns"""
        prices = list(self.prices)
        
        # Calculate consecutive streak
        streak_direction, streak_count = self._calculate_streak(prices)
        
        # Calculate momentum at different windows
        short_momentum = self._calculate_momentum(prices, self.SHORT_WINDOW)
        medium_momentum = self._calculate_momentum(prices, self.MEDIUM_WINDOW)
        long_momentum = self._calculate_momentum(prices, self.LONG_WINDOW)
        
        # Detect pattern type
        pattern = self._detect_pattern(prices, short_momentum, medium_momentum, long_momentum)
        
        # Calculate volatility
        volatility = self._calculate_volatility(prices)
        vol_percentile = self._volatility_percentile(prices)
        
        # Support/Resistance levels
        support, resistance = self._find_sr_levels(prices)
        
        # Pattern data
        pattern_data = {
            "streak_direction": streak_direction,
            "streak_count": streak_count,
            "short_momentum": short_momentum,
            "medium_momentum": medium_momentum,
            "long_momentum": long_momentum,
            "pattern": pattern,
            "volatility": volatility,
            "vol_percentile": vol_percentile,
            "support": support,
            "resistance": resistance,
            "current_price": prices[-1]
        }
        
        signal = None
        
        # Strategy 1: Reversal after extended streak
        if streak_count >= self.REVERSAL_STREAK:
            opposite_direction = "SELL" if streak_direction == "UP" else "BUY"
            confidence = 0.55 + min(streak_count - 5, 5) * 0.03
            
            signal = TickSignal(
                direction=opposite_direction,
                signal_type="reversal",
                confidence=confidence,
                reason=f"Reversal after {streak_count} {streak_direction} ticks",
                pattern_data=pattern_data,
                timestamp=time.time(),
                symbol=self.symbol
            )
        
        # Strategy 2: Continuation with accelerating momentum
        elif pattern == "acceleration" and streak_count >= self.MIN_STREAK:
            direction = "BUY" if short_momentum > 0 else "SELL"
            confidence = 0.60 + abs(short_momentum) * 10
            confidence = min(0.75, confidence)
            
            signal = TickSignal(
                direction=direction,
                signal_type="continuation",
                confidence=confidence,
                reason=f"Momentum acceleration: {short_momentum:.4f}",
                pattern_data=pattern_data,
                timestamp=time.time(),
                symbol=self.symbol
            )
        
        # Strategy 3: Breakout from consolidation
        elif pattern == "breakout":
            direction = "BUY" if prices[-1] > prices[-2] else "SELL"
            confidence = 0.65
            
            signal = TickSignal(
                direction=direction,
                signal_type="breakout",
                confidence=confidence,
                reason=f"Breakout from consolidation",
                pattern_data=pattern_data,
                timestamp=time.time(),
                symbol=self.symbol
            )
        
        # Strategy 4: Support/Resistance bounce
        elif pattern == "sr_bounce":
            current = prices[-1]
            if support and abs(current - support) < volatility:
                signal = TickSignal(
                    direction="BUY",
                    signal_type="reversal",
                    confidence=0.60,
                    reason=f"Support bounce at {support:.2f}",
                    pattern_data=pattern_data,
                    timestamp=time.time(),
                    symbol=self.symbol
                )
            elif resistance and abs(current - resistance) < volatility:
                signal = TickSignal(
                    direction="SELL",
                    signal_type="reversal",
                    confidence=0.60,
                    reason=f"Resistance rejection at {resistance:.2f}",
                    pattern_data=pattern_data,
                    timestamp=time.time(),
                    symbol=self.symbol
                )
        
        if signal and signal.confidence >= 0.55:
            self.last_signal_time = signal.timestamp
            logger.info(
                f"[TICK {self.symbol}] Signal: {signal.direction} "
                f"Type: {signal.signal_type} | "
                f"Confidence: {signal.confidence:.2f} | "
                f"Reason: {signal.reason}"
            )
            return signal
        
        return None
    
    def _calculate_streak(self, prices: List[float]) -> tuple:
        """Calculate consecutive up/down streak"""
        if len(prices) < 2:
            return "NONE", 0
        
        streak_count = 1
        last_direction = "UP" if prices[-1] > prices[-2] else "DOWN"
        
        for i in range(len(prices) - 2, 0, -1):
            if prices[i] == prices[i - 1]:
                continue
            
            current_direction = "UP" if prices[i] > prices[i - 1] else "DOWN"
            if current_direction == last_direction:
                streak_count += 1
            else:
                break
        
        return last_direction, streak_count
    
    def _calculate_momentum(self, prices: List[float], window: int) -> float:
        """Calculate price momentum over window"""
        if len(prices) < window:
            return 0
        
        recent = prices[-window:]
        return (recent[-1] - recent[0]) / recent[0] if recent[0] != 0 else 0
    
    def _calculate_volatility(self, prices: List[float], window: int = 20) -> float:
        """Calculate price volatility"""
        if len(prices) < window:
            return 0
        
        recent = prices[-window:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        return variance ** 0.5
    
    def _volatility_percentile(self, prices: List[float]) -> float:
        """Calculate current volatility percentile"""
        if len(prices) < 50:
            return 50
        
        volatilities = []
        for i in range(20, len(prices)):
            window = prices[i-20:i]
            mean = sum(window) / 20
            variance = sum((p - mean) ** 2 for p in window) / 20
            volatilities.append(variance ** 0.5)
        
        current_vol = volatilities[-1]
        below_count = sum(1 for v in volatilities if v < current_vol)
        return (below_count / len(volatilities)) * 100
    
    def _detect_pattern(
        self,
        prices: List[float],
        short_mom: float,
        medium_mom: float,
        long_mom: float
    ) -> str:
        """Detect price pattern"""
        # Acceleration: short momentum stronger than medium
        if abs(short_mom) > abs(medium_mom) * 1.5 and abs(short_mom) > 0.001:
            return "acceleration"
        
        # Consolidation: low volatility
        vol = self._calculate_volatility(prices, 10)
        avg_vol = self._calculate_volatility(prices, 50)
        
        if vol < avg_vol * 0.5:
            # Check for breakout
            recent_range = max(prices[-10:]) - min(prices[-10:])
            if prices[-1] > max(prices[-11:-1]) or prices[-1] < min(prices[-11:-1]):
                return "breakout"
            return "consolidation"
        
        # Trending
        if all(m > 0 for m in [short_mom, medium_mom, long_mom]):
            return "uptrend"
        elif all(m < 0 for m in [short_mom, medium_mom, long_mom]):
            return "downtrend"
        
        # S/R bounce detection
        support, resistance = self._find_sr_levels(prices)
        current = prices[-1]
        vol = self._calculate_volatility(prices)
        
        if support and abs(current - support) < vol * 2:
            return "sr_bounce"
        if resistance and abs(current - resistance) < vol * 2:
            return "sr_bounce"
        
        return "ranging"
    
    def _find_sr_levels(self, prices: List[float]) -> tuple:
        """Find support and resistance levels"""
        if len(prices) < 20:
            return None, None
        
        recent = prices[-50:] if len(prices) >= 50 else prices
        
        # Simple S/R: local min/max
        support = min(recent)
        resistance = max(recent)
        
        return support, resistance
    
    def get_analysis(self) -> Dict[str, Any]:
        """Get current tick analysis"""
        if len(self.prices) < self.LONG_WINDOW:
            return {"status": "insufficient_data", "ticks": len(self.prices)}
        
        prices = list(self.prices)
        streak_dir, streak_count = self._calculate_streak(prices)
        
        return {
            "status": "ready",
            "ticks": len(prices),
            "current_price": prices[-1],
            "streak_direction": streak_dir,
            "streak_count": streak_count,
            "short_momentum": self._calculate_momentum(prices, self.SHORT_WINDOW),
            "medium_momentum": self._calculate_momentum(prices, self.MEDIUM_WINDOW),
            "long_momentum": self._calculate_momentum(prices, self.LONG_WINDOW),
            "volatility": self._calculate_volatility(prices),
            "vol_percentile": self._volatility_percentile(prices),
            "pattern": self._detect_pattern(
                prices,
                self._calculate_momentum(prices, self.SHORT_WINDOW),
                self._calculate_momentum(prices, self.MEDIUM_WINDOW),
                self._calculate_momentum(prices, self.LONG_WINDOW)
            )
        }
    
    def reset(self):
        """Reset strategy state"""
        self.tick_history.clear()
        self.prices.clear()
        self.last_signal_time = 0
        logger.info(f"[TICK {self.symbol}] Strategy reset")
