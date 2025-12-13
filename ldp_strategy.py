"""
LDP Strategy - Last Digit Prediction based on frequency analysis
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from collections import deque, Counter

logger = logging.getLogger(__name__)

@dataclass
class LDPSignal:
    """LDP trading signal"""
    contract_type: str  # DIGITOVER, DIGITUNDER, DIGITMATCH, DIGITDIFF, DIGITEVEN, DIGITODD
    barrier: Optional[int]  # Digit for OVER/UNDER/MATCH/DIFF
    confidence: float
    reason: str
    digit_stats: Dict[str, Any]
    timestamp: float
    symbol: str

class LDPStrategy:
    """
    Last Digit Prediction Strategy
    
    Analyzes the last digit of tick prices to find patterns and predict
    the next digit for binary options trading.
    
    Contract Types:
    - DIGITOVER: Last digit > barrier
    - DIGITUNDER: Last digit < barrier  
    - DIGITMATCH: Last digit = barrier (high risk/reward)
    - DIGITDIFF: Last digit != barrier (safe on cold digits)
    - DIGITEVEN: Last digit is even (0,2,4,6,8)
    - DIGITODD: Last digit is odd (1,3,5,7,9)
    """
    
    MIN_TICKS = 150  # Require statistical significance (150+ samples)
    HOT_THRESHOLD = 0.18  # Hot digit = appears more than 18% (clear outlier)
    COLD_THRESHOLD = 0.05  # Cold digit = appears less than 5% (clear outlier)
    STREAK_THRESHOLD = 4  # Require meaningful streak
    ZONE_IMBALANCE_THRESHOLD = 0.15  # Significant imbalance required
    
    def __init__(self, symbol: str = "R_100"):
        self.symbol = symbol
        self.digit_history: deque = deque(maxlen=500)  # Larger sample for significance
        self.tick_history: deque = deque(maxlen=500)
        self.last_signal_time = 0
        self.signal_cooldown = 30  # Proper cooldown for sample collection
    
    def _get_last_digit(self, price: float) -> int:
        """Extract last digit from price"""
        price_str = f"{price:.2f}"
        return int(price_str[-1])
    
    def add_tick(self, tick: Dict[str, Any]) -> Optional[LDPSignal]:
        """Add tick and analyze for LDP signals"""
        quote = tick.get("quote", 0)
        if quote <= 0:
            return None
        
        digit = self._get_last_digit(quote)
        self.digit_history.append(digit)
        self.tick_history.append(tick)
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_signal_time < self.signal_cooldown:
            return None
        
        # Need minimum data
        if len(self.digit_history) < self.MIN_TICKS:
            return None
        
        return self._analyze()
    
    def _analyze(self) -> Optional[LDPSignal]:
        """Analyze digit patterns and generate signal"""
        digits = list(self.digit_history)
        
        # Calculate frequencies
        counter = Counter(digits)
        total = len(digits)
        frequencies = {d: counter.get(d, 0) / total for d in range(10)}
        
        # Identify hot and cold digits
        hot_digits = [d for d, f in frequencies.items() if f >= self.HOT_THRESHOLD]
        cold_digits = [d for d, f in frequencies.items() if f <= self.COLD_THRESHOLD]
        
        # Zone analysis (Low: 0-4, High: 5-9)
        low_zone = sum(counter.get(d, 0) for d in range(5))
        high_zone = sum(counter.get(d, 0) for d in range(5, 10))
        low_pct = low_zone / total
        high_pct = high_zone / total
        zone_imbalance = abs(low_pct - high_pct)
        
        # Even/Odd analysis
        even_count = sum(counter.get(d, 0) for d in [0, 2, 4, 6, 8])
        odd_count = sum(counter.get(d, 0) for d in [1, 3, 5, 7, 9])
        even_pct = even_count / total
        odd_pct = odd_count / total
        
        # Streak analysis
        streak_digit = digits[-1]
        streak_count = 1
        for d in reversed(list(digits)[:-1]):
            if d == streak_digit:
                streak_count += 1
            else:
                break
        
        # Zone streak
        recent_10 = digits[-10:]
        low_streak = sum(1 for d in recent_10 if d < 5)
        high_streak = sum(1 for d in recent_10 if d >= 5)
        
        # Build digit stats
        digit_stats = {
            "frequencies": frequencies,
            "hot_digits": hot_digits,
            "cold_digits": cold_digits,
            "low_zone_pct": low_pct,
            "high_zone_pct": high_pct,
            "zone_imbalance": zone_imbalance,
            "even_pct": even_pct,
            "odd_pct": odd_pct,
            "last_digit": digits[-1],
            "streak_digit": streak_digit,
            "streak_count": streak_count,
            "low_streak": low_streak,
            "high_streak": high_streak
        }
        
        # Generate signal based on patterns
        signal = None
        
        # Strategy 1: Cold digit DIFF (high confidence)
        if cold_digits:
            coldest = min(cold_digits, key=lambda d: frequencies[d])
            confidence = 0.85 - frequencies[coldest]
            signal = LDPSignal(
                contract_type="DIGITDIFF",
                barrier=coldest,
                confidence=confidence,
                reason=f"Cold digit {coldest} ({frequencies[coldest]*100:.1f}%)",
                digit_stats=digit_stats,
                timestamp=time.time(),
                symbol=self.symbol
            )
        
        # Strategy 2: Zone reversal after imbalance
        elif zone_imbalance >= self.ZONE_IMBALANCE_THRESHOLD:
            if low_pct > high_pct:
                # Expect high zone
                signal = LDPSignal(
                    contract_type="DIGITOVER",
                    barrier=4,
                    confidence=0.65 + zone_imbalance * 0.2,
                    reason=f"Zone reversal: Low dominant ({low_pct*100:.1f}%)",
                    digit_stats=digit_stats,
                    timestamp=time.time(),
                    symbol=self.symbol
                )
            else:
                # Expect low zone
                signal = LDPSignal(
                    contract_type="DIGITUNDER",
                    barrier=5,
                    confidence=0.65 + zone_imbalance * 0.2,
                    reason=f"Zone reversal: High dominant ({high_pct*100:.1f}%)",
                    digit_stats=digit_stats,
                    timestamp=time.time(),
                    symbol=self.symbol
                )
        
        # Strategy 3: Even/Odd imbalance
        elif abs(even_pct - odd_pct) > 0.2:
            if even_pct > odd_pct:
                signal = LDPSignal(
                    contract_type="DIGITODD",
                    barrier=None,
                    confidence=0.60 + abs(even_pct - odd_pct) * 0.3,
                    reason=f"Even dominant ({even_pct*100:.1f}%), expect odd",
                    digit_stats=digit_stats,
                    timestamp=time.time(),
                    symbol=self.symbol
                )
            else:
                signal = LDPSignal(
                    contract_type="DIGITEVEN",
                    barrier=None,
                    confidence=0.60 + abs(even_pct - odd_pct) * 0.3,
                    reason=f"Odd dominant ({odd_pct*100:.1f}%), expect even",
                    digit_stats=digit_stats,
                    timestamp=time.time(),
                    symbol=self.symbol
                )
        
        # Strategy 4: Streak reversal
        elif streak_count >= self.STREAK_THRESHOLD:
            # After long streak, expect different digit
            signal = LDPSignal(
                contract_type="DIGITDIFF",
                barrier=streak_digit,
                confidence=0.70 + min(streak_count - 4, 3) * 0.05,
                reason=f"Streak of {streak_count}x digit {streak_digit}",
                digit_stats=digit_stats,
                timestamp=time.time(),
                symbol=self.symbol
            )
        
        if signal and signal.confidence >= 0.30:
            self.last_signal_time = signal.timestamp
            logger.info(
                f"[LDP {self.symbol}] Signal: {signal.contract_type} "
                f"Barrier: {signal.barrier} | "
                f"Confidence: {signal.confidence:.2f} | "
                f"Reason: {signal.reason}"
            )
            return signal
        
        return None
    
    def get_digit_heatmap(self) -> Dict[int, float]:
        """Get frequency heatmap for digits 0-9"""
        if len(self.digit_history) < 10:
            return {d: 0.1 for d in range(10)}
        
        counter = Counter(self.digit_history)
        total = len(self.digit_history)
        return {d: counter.get(d, 0) / total for d in range(10)}
    
    def get_analysis(self) -> Dict[str, Any]:
        """Get current digit analysis"""
        if len(self.digit_history) < 10:
            return {"status": "insufficient_data", "ticks": len(self.digit_history)}
        
        digits = list(self.digit_history)
        counter = Counter(digits)
        total = len(digits)
        frequencies = {d: counter.get(d, 0) / total for d in range(10)}
        
        hot_digits = [d for d, f in frequencies.items() if f >= self.HOT_THRESHOLD]
        cold_digits = [d for d, f in frequencies.items() if f <= self.COLD_THRESHOLD]
        
        low_zone = sum(counter.get(d, 0) for d in range(5)) / total
        high_zone = sum(counter.get(d, 0) for d in range(5, 10)) / total
        
        even_count = sum(counter.get(d, 0) for d in [0, 2, 4, 6, 8]) / total
        odd_count = sum(counter.get(d, 0) for d in [1, 3, 5, 7, 9]) / total
        
        return {
            "status": "ready",
            "ticks": len(self.digit_history),
            "frequencies": frequencies,
            "hot_digits": hot_digits,
            "cold_digits": cold_digits,
            "low_zone_pct": low_zone,
            "high_zone_pct": high_zone,
            "even_pct": even_count,
            "odd_pct": odd_count,
            "last_digit": digits[-1],
            "recent_10": digits[-10:]
        }
    
    def reset(self):
        """Reset strategy state"""
        self.digit_history.clear()
        self.tick_history.clear()
        self.last_signal_time = 0
        logger.info(f"[LDP {self.symbol}] Strategy reset")
