"""
DigitPad Strategy - Advanced digit frequency analysis with heatmap
Based on https://binarybot.live/digitpad/
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from collections import deque, Counter
import time
import math

logger = logging.getLogger(__name__)


@dataclass
class DigitSignal:
    contract_type: str  # DIGITOVER, DIGITUNDER, DIGITMATCH, DIGITDIFF, DIGITEVEN, DIGITODD
    digit: Optional[int]  # Target digit (0-9)
    confidence: float  # 0.0 - 1.0
    pattern_type: str  # HOT, COLD, STREAK, EVEN_DOMINANT, ODD_DOMINANT
    analysis: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "digit": self.digit,
            "confidence": self.confidence,
            "pattern_type": self.pattern_type,
            "analysis": self.analysis,
            "timestamp": self.timestamp
        }


class DigitPadStrategy:
    """
    DigitPad Strategy - Digit frequency analysis with visual heatmap
    
    Features:
    - Multi-symbol digit tracking (10v, 25v, 50v, 75v, 100v, 10(1s), etc.)
    - Real-time digit frequency heatmap
    - Hot/Cold digit detection
    - Even/Odd analysis
    - Pattern-based signals
    - Signals Chart integration
    """
    
    # Thresholds
    HOT_THRESHOLD = 0.15  # 15% frequency = hot
    COLD_THRESHOLD = 0.05  # 5% frequency = cold
    STREAK_THRESHOLD = 3
    ZONE_IMBALANCE_THRESHOLD = 0.25
    MIN_CONFIDENCE = 0.60
    MIN_TICKS = 100
    
    # Supported symbols
    SUPPORTED_SYMBOLS = [
        "R_10", "R_25", "R_50", "R_75", "R_100",
        "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V"
    ]
    
    def __init__(self):
        # Per-symbol tracking
        self.symbol_data: Dict[str, Dict] = {}
        
        # Initialize all symbols
        for symbol in self.SUPPORTED_SYMBOLS:
            self._init_symbol(symbol)
        
        # Signal history
        self.signals: deque = deque(maxlen=100)
        self.last_signal_time = 0
        self.signal_cooldown = 5  # seconds
    
    def _init_symbol(self, symbol: str):
        """Initialize tracking for a symbol"""
        self.symbol_data[symbol] = {
            "digits": deque(maxlen=100),
            "frequency": Counter(),
            "streak": {"digit": None, "count": 0},
            "even_count": 0,
            "odd_count": 0,
            "last_tick": None
        }
    
    def add_tick(self, symbol: str, tick: Dict[str, Any]):
        """Add tick data for a symbol"""
        if symbol not in self.symbol_data:
            self._init_symbol(symbol)
        
        price = tick.get("quote", tick.get("price", 0))
        if price <= 0:
            return
        
        # Extract last digit
        price_str = f"{price:.5f}"
        last_digit = int(price_str[-1])
        
        data = self.symbol_data[symbol]
        data["digits"].append(last_digit)
        data["frequency"][last_digit] += 1
        data["last_tick"] = tick
        
        # Update even/odd counts
        if last_digit % 2 == 0:
            data["even_count"] += 1
        else:
            data["odd_count"] += 1
        
        # Update streak
        if data["streak"]["digit"] == last_digit:
            data["streak"]["count"] += 1
        else:
            data["streak"]["digit"] = last_digit
            data["streak"]["count"] = 1
    
    def get_heatmap(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get digit frequency heatmap for a symbol
        
        Returns list of digit data with frequency and color coding
        """
        if symbol not in self.symbol_data:
            return []
        
        data = self.symbol_data[symbol]
        total = sum(data["frequency"].values())
        
        if total == 0:
            return [{"digit": i, "count": 0, "frequency": 0, "status": "neutral"} for i in range(10)]
        
        heatmap = []
        for digit in range(10):
            count = data["frequency"][digit]
            freq = count / total
            
            if freq >= self.HOT_THRESHOLD:
                status = "hot"
            elif freq <= self.COLD_THRESHOLD:
                status = "cold"
            else:
                status = "neutral"
            
            heatmap.append({
                "digit": digit,
                "count": count,
                "frequency": round(freq * 100, 1),
                "status": status
            })
        
        return heatmap
    
    def get_multi_symbol_heatmap(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get heatmap for all symbols"""
        return {symbol: self.get_heatmap(symbol) for symbol in self.SUPPORTED_SYMBOLS}
    
    def analyze(self, symbol: str) -> Optional[DigitSignal]:
        """
        Analyze digit patterns and generate signal
        
        Args:
            symbol: Trading symbol
            
        Returns:
            DigitSignal if pattern detected, else None
        """
        if symbol not in self.symbol_data:
            return None
        
        data = self.symbol_data[symbol]
        
        if len(data["digits"]) < self.MIN_TICKS:
            return None
        
        # Check cooldown
        if time.time() - self.last_signal_time < self.signal_cooldown:
            return None
        
        # Get heatmap and analysis
        heatmap = self.get_heatmap(symbol)
        total = sum(data["frequency"].values())
        
        # Analyze patterns
        signal = None
        
        # 1. Hot Digit Pattern - bet DIGITDIFF on hot digits (reversal expected)
        hot_digits = [h["digit"] for h in heatmap if h["status"] == "hot"]
        if hot_digits:
            hottest = max(hot_digits, key=lambda d: data["frequency"][d])
            confidence = data["frequency"][hottest] / total
            if confidence > self.MIN_CONFIDENCE:
                signal = DigitSignal(
                    contract_type="DIGITDIFF",
                    digit=hottest,
                    confidence=min(confidence, 0.90),
                    pattern_type="HOT",
                    analysis={
                        "hot_digit": hottest,
                        "frequency": round(confidence * 100, 1),
                        "reason": f"Digit {hottest} is overheated, expect reversal"
                    }
                )
        
        # 2. Cold Digit Pattern - bet DIGITMATCH on cold digits (due for appearance)
        cold_digits = [h["digit"] for h in heatmap if h["status"] == "cold"]
        if cold_digits and not signal:
            coldest = min(cold_digits, key=lambda d: data["frequency"][d])
            cold_freq = data["frequency"][coldest] / total if total > 0 else 0
            # Cold digit match has lower confidence but higher payout
            confidence = 0.25 + (0.10 - cold_freq) * 2  # Boost for very cold
            if confidence > 0.20:  # Lower threshold for high-payout trade
                signal = DigitSignal(
                    contract_type="DIGITMATCH",
                    digit=coldest,
                    confidence=min(confidence, 0.35),
                    pattern_type="COLD",
                    analysis={
                        "cold_digit": coldest,
                        "frequency": round(cold_freq * 100, 1),
                        "reason": f"Digit {coldest} is cold, due for appearance"
                    }
                )
        
        # 3. Streak Pattern - bet against streak continuation
        streak = data["streak"]
        if streak["count"] >= self.STREAK_THRESHOLD and not signal:
            confidence = 0.60 + (streak["count"] - 3) * 0.05
            signal = DigitSignal(
                contract_type="DIGITDIFF",
                digit=streak["digit"],
                confidence=min(confidence, 0.85),
                pattern_type="STREAK",
                analysis={
                    "streak_digit": streak["digit"],
                    "streak_count": streak["count"],
                    "reason": f"Digit {streak['digit']} streaked {streak['count']}x, expect break"
                }
            )
        
        # 4. Even/Odd Imbalance
        even = data["even_count"]
        odd = data["odd_count"]
        total_eo = even + odd
        
        if total_eo > 50 and not signal:
            even_ratio = even / total_eo
            odd_ratio = odd / total_eo
            
            if even_ratio > 0.5 + self.ZONE_IMBALANCE_THRESHOLD:
                # Even dominant, bet ODD
                confidence = 0.60 + (even_ratio - 0.6) * 0.5
                signal = DigitSignal(
                    contract_type="DIGITODD",
                    digit=None,
                    confidence=min(confidence, 0.80),
                    pattern_type="EVEN_DOMINANT",
                    analysis={
                        "even_ratio": round(even_ratio * 100, 1),
                        "odd_ratio": round(odd_ratio * 100, 1),
                        "reason": f"Even dominant ({even_ratio*100:.0f}%), bet ODD"
                    }
                )
            elif odd_ratio > 0.5 + self.ZONE_IMBALANCE_THRESHOLD:
                # Odd dominant, bet EVEN
                confidence = 0.60 + (odd_ratio - 0.6) * 0.5
                signal = DigitSignal(
                    contract_type="DIGITEVEN",
                    digit=None,
                    confidence=min(confidence, 0.80),
                    pattern_type="ODD_DOMINANT",
                    analysis={
                        "even_ratio": round(even_ratio * 100, 1),
                        "odd_ratio": round(odd_ratio * 100, 1),
                        "reason": f"Odd dominant ({odd_ratio*100:.0f}%), bet EVEN"
                    }
                )
        
        if signal and signal.confidence >= self.MIN_CONFIDENCE:
            self.signals.append(signal)
            self.last_signal_time = time.time()
            logger.info(f"DigitPad Signal: {signal.contract_type} digit={signal.digit} @ {signal.confidence*100:.1f}%")
            return signal
        
        return None
    
    def get_signals_chart(self, symbol: str) -> Dict[str, Any]:
        """
        Generate Signals Chart data
        
        Shows:
        - Differ: 50% (Natural)
        - Differ: 30% (min) - Not Good
        - Differ: 70% (max) - Strong Buy
        """
        if symbol not in self.symbol_data:
            return {}
        
        data = self.symbol_data[symbol]
        total = sum(data["frequency"].values())
        
        if total == 0:
            return {"differ_natural": 50, "differ_min": 30, "differ_max": 70}
        
        # Calculate differ percentages based on digit distribution
        hot_digits = [d for d in range(10) if data["frequency"][d] / total > self.HOT_THRESHOLD]
        cold_digits = [d for d in range(10) if data["frequency"][d] / total < self.COLD_THRESHOLD]
        
        # Differ probability based on distribution
        hot_count = len(hot_digits)
        cold_count = len(cold_digits)
        
        if hot_count >= 2:
            # High differ probability when multiple hot digits
            differ_max = min(90, 50 + hot_count * 10)
        else:
            differ_max = 70
        
        if cold_count >= 3:
            differ_min = max(20, 30 - cold_count * 3)
        else:
            differ_min = 30
        
        return {
            "differ_natural": 50,
            "differ_min": differ_min,
            "differ_max": differ_max,
            "hot_count": hot_count,
            "cold_count": cold_count,
            "recommendation": "Strong Buy" if differ_max >= 70 else "Natural" if differ_max >= 50 else "Not Good"
        }
    
    def get_stats(self, symbol: str) -> Dict[str, Any]:
        """Get statistics for a symbol"""
        if symbol not in self.symbol_data:
            return {}
        
        data = self.symbol_data[symbol]
        total = sum(data["frequency"].values())
        
        return {
            "symbol": symbol,
            "ticks_count": len(data["digits"]),
            "total_digits": total,
            "even_count": data["even_count"],
            "odd_count": data["odd_count"],
            "current_streak": data["streak"],
            "heatmap": self.get_heatmap(symbol),
            "signals_chart": self.get_signals_chart(symbol)
        }
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all symbols"""
        return {symbol: self.get_stats(symbol) for symbol in self.SUPPORTED_SYMBOLS}
