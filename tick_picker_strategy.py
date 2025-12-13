"""
Tick Picker Strategy - Tick pattern analysis with trend detection
Based on https://binarybot.live/tick-picker/
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import deque
import time
import math

logger = logging.getLogger(__name__)


@dataclass
class TickPickerSignal:
    direction: str  # "BUY" or "SELL"
    confidence: float
    pattern: str  # "UPTREND", "DOWNTREND", "REVERSAL", "CONTINUATION"
    streak: int
    momentum: float
    entry_price: float
    analysis: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "confidence": self.confidence,
            "pattern": self.pattern,
            "streak": self.streak,
            "momentum": self.momentum,
            "entry_price": self.entry_price,
            "analysis": self.analysis,
            "timestamp": self.timestamp
        }


class TickPickerStrategy:
    """
    Tick Picker Strategy - Real-time tick pattern analysis
    
    Features:
    - Live tick chart with trend detection
    - Consecutive tick streak tracking
    - Multi-timeframe momentum analysis
    - Pattern recognition (Uptrend, Downtrend, Reversal, Consolidation)
    - Fixed stake / Martingale support
    """
    
    # Analysis windows
    SHORT_WINDOW = 5
    MEDIUM_WINDOW = 10
    LONG_WINDOW = 20
    
    # Thresholds - STRICT for quality signals
    STREAK_THRESHOLD = 3  # Require meaningful streak
    REVERSAL_THRESHOLD = 5  # Require extended streak for reversal
    MIN_CONFIDENCE = 0.60  # Require moderate confidence
    MIN_TICKS = 30  # Proper warmup for pattern accuracy
    
    def __init__(self, symbol: str = "R_100"):
        self.symbol = symbol
        self.ticks: deque = deque(maxlen=200)
        self.prices: List[float] = []
        self.directions: List[int] = []  # 1=up, -1=down, 0=same
        
        # Pattern tracking
        self.current_streak = 0
        self.streak_direction = 0  # 1=up, -1=down
        self.last_price = 0
        
        # Signal history
        self.signals: deque = deque(maxlen=100)
        self.last_signal_time = 0
        self.signal_cooldown = 10  # Proper cooldown for pattern confirmation
        
        # Money management
        self.use_martingale = False
        self.base_stake = 1.0
        self.current_level = 0
        self.max_level = 5
        self.multiplier = 2.0
    
    def add_tick(self, tick: Dict[str, Any]):
        """Add new tick data"""
        price = tick.get("quote", tick.get("price", 0))
        if price <= 0:
            return
        
        self.ticks.append(tick)
        self.prices.append(price)
        
        # Calculate direction
        if self.last_price > 0:
            if price > self.last_price:
                direction = 1
            elif price < self.last_price:
                direction = -1
            else:
                direction = 0
            
            self.directions.append(direction)
            
            # Update streak
            if direction != 0:
                if direction == self.streak_direction:
                    self.current_streak += 1
                else:
                    self.streak_direction = direction
                    self.current_streak = 1
        
        self.last_price = price
        
        # Trim lists
        if len(self.prices) > 200:
            self.prices = self.prices[-200:]
        if len(self.directions) > 200:
            self.directions = self.directions[-200:]
        
        # Analyze for trading signal
        return self.analyze()
    
    def analyze(self) -> Optional[TickPickerSignal]:
        """
        Analyze tick patterns
        
        Returns:
            TickPickerSignal if pattern detected
        """
        if len(self.prices) < self.MIN_TICKS:
            return None
        
        # Check cooldown
        if time.time() - self.last_signal_time < self.signal_cooldown:
            return None
        
        # Calculate momentum for different timeframes
        short_momentum = self._calculate_momentum(self.SHORT_WINDOW)
        medium_momentum = self._calculate_momentum(self.MEDIUM_WINDOW)
        long_momentum = self._calculate_momentum(self.LONG_WINDOW)
        
        # Detect pattern
        pattern, confidence = self._detect_pattern(short_momentum, medium_momentum, long_momentum)
        
        if pattern is None or confidence < self.MIN_CONFIDENCE:
            return None
        
        # Determine direction
        direction = self._get_direction_from_pattern(pattern, short_momentum)
        
        if direction is None:
            return None
        
        signal = TickPickerSignal(
            direction=direction,
            confidence=confidence,
            pattern=pattern,
            streak=self.current_streak,
            momentum=short_momentum,
            entry_price=self.prices[-1],
            analysis={
                "short_momentum": round(short_momentum, 4),
                "medium_momentum": round(medium_momentum, 4),
                "long_momentum": round(long_momentum, 4),
                "streak_direction": "UP" if self.streak_direction > 0 else "DOWN",
                "streak_count": self.current_streak
            }
        )
        
        self.signals.append(signal)
        self.last_signal_time = time.time()
        
        logger.info(f"TickPicker Signal: {direction} pattern={pattern} @ {confidence*100:.1f}%")
        
        return signal
    
    def _calculate_momentum(self, window: int) -> float:
        """Calculate momentum for given window"""
        if len(self.prices) < window + 1:
            return 0
        
        recent = self.prices[-window:]
        oldest = self.prices[-(window+1)]
        
        if oldest == 0:
            return 0
        
        return (recent[-1] - oldest) / oldest * 100
    
    def _detect_pattern(self, short_mom: float, med_mom: float, long_mom: float) -> tuple:
        """
        Detect market pattern with STRICT streak enforcement
        
        Returns:
            (pattern_name, confidence)
        """
        # STRICT: Require minimum streak for any pattern except trend
        # Reversal Detection - ONLY if streak threshold met
        if self.current_streak >= self.REVERSAL_THRESHOLD:
            # Long streak, expect reversal - confidence starts lower
            base_confidence = 0.55
            streak_bonus = min((self.current_streak - self.REVERSAL_THRESHOLD) * 0.04, 0.20)
            confidence = base_confidence + streak_bonus
            return ("REVERSAL", min(confidence, 0.80))
        
        # STRICT: Momentum must exceed minimum threshold for trend detection
        min_momentum = 0.001  # Minimum momentum threshold
        
        # Trend Detection - require meaningful momentum
        if short_mom > min_momentum and med_mom > min_momentum and long_mom > min_momentum:
            alignment = min(abs(short_mom), abs(med_mom), abs(long_mom))
            # STRICT: Start lower, require momentum strength
            if alignment < 0.002:
                return (None, 0)  # Too weak
            confidence = 0.50 + min(alignment * 15, 0.25)
            return ("UPTREND", min(confidence, 0.75))
        
        if short_mom < -min_momentum and med_mom < -min_momentum and long_mom < -min_momentum:
            alignment = min(abs(short_mom), abs(med_mom), abs(long_mom))
            if alignment < 0.002:
                return (None, 0)  # Too weak
            confidence = 0.50 + min(alignment * 15, 0.25)
            return ("DOWNTREND", min(confidence, 0.75))
        
        # Continuation - STRICT: Must meet STREAK_THRESHOLD
        if self.current_streak >= self.STREAK_THRESHOLD:
            # STRICT: Require momentum acceleration
            if abs(short_mom) > abs(long_mom) * 1.3:  # 30% acceleration required
                base_confidence = 0.50
                streak_bonus = min((self.current_streak - self.STREAK_THRESHOLD) * 0.03, 0.15)
                mom_bonus = min(abs(short_mom) * 5, 0.10)
                confidence = base_confidence + streak_bonus + mom_bonus
                return ("CONTINUATION", min(confidence, 0.70))
        
        # Consolidation - no signal for low confidence
        if abs(short_mom) < 0.01 and abs(med_mom) < 0.02:
            return ("CONSOLIDATION", 0.40)  # Below MIN_CONFIDENCE, won't generate signal
        
        return (None, 0)
    
    def _get_direction_from_pattern(self, pattern: str, short_momentum: float) -> Optional[str]:
        """Get trade direction based on pattern"""
        if pattern == "REVERSAL":
            # Trade against the streak
            return "SELL" if self.streak_direction > 0 else "BUY"
        
        elif pattern == "UPTREND":
            return "BUY"
        
        elif pattern == "DOWNTREND":
            return "SELL"
        
        elif pattern == "CONTINUATION":
            return "BUY" if self.streak_direction > 0 else "SELL"
        
        return None
    
    def get_chart_data(self) -> Dict[str, Any]:
        """Get data for tick chart visualization"""
        if len(self.prices) < 2:
            return {}
        
        # Get last 50 ticks for chart
        chart_prices = self.prices[-50:]
        chart_times = list(range(len(chart_prices)))
        
        # Calculate trend line
        if len(chart_prices) >= 10:
            n = len(chart_prices)
            sum_x = sum(chart_times)
            sum_y = sum(chart_prices)
            sum_xy = sum(x * y for x, y in zip(chart_times, chart_prices))
            sum_x2 = sum(x * x for x in chart_times)
            
            slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x) if (n * sum_x2 - sum_x * sum_x) != 0 else 0
            intercept = (sum_y - slope * sum_x) / n
            
            trend_line = [slope * x + intercept for x in chart_times]
        else:
            trend_line = chart_prices
        
        return {
            "prices": chart_prices,
            "times": chart_times,
            "trend_line": trend_line,
            "last_price": self.prices[-1] if self.prices else 0,
            "current_streak": self.current_streak,
            "streak_direction": "UP" if self.streak_direction > 0 else "DOWN" if self.streak_direction < 0 else "NONE"
        }
    
    def get_stake(self) -> float:
        """Get current stake (supports Martingale)"""
        if not self.use_martingale:
            return self.base_stake
        
        return self.base_stake * (self.multiplier ** self.current_level)
    
    def record_result(self, won: bool):
        """Record trade result for Martingale"""
        if won:
            self.current_level = 0
        else:
            self.current_level = min(self.current_level + 1, self.max_level)
    
    def set_martingale(self, enabled: bool, base_stake: float = 1.0, multiplier: float = 2.0, max_level: int = 5):
        """Configure Martingale settings"""
        self.use_martingale = enabled
        self.base_stake = base_stake
        self.multiplier = multiplier
        self.max_level = max_level
    
    def get_stats(self) -> Dict[str, Any]:
        """Get strategy statistics"""
        return {
            "symbol": self.symbol,
            "ticks_count": len(self.ticks),
            "signals_count": len(self.signals),
            "current_streak": self.current_streak,
            "streak_direction": "UP" if self.streak_direction > 0 else "DOWN",
            "last_price": self.last_price,
            "use_martingale": self.use_martingale,
            "current_level": self.current_level,
            "chart_data": self.get_chart_data()
        }
