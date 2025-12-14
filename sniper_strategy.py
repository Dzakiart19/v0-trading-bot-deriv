"""
Sniper Strategy - Ultra-selective high probability trading
Based on https://binarybot.live/sniper/
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
import time
import math

from indicators import TechnicalIndicators
from strategy import DynamicThresholds

logger = logging.getLogger(__name__)


class MoneyManagement(Enum):
    FIXED_STAKE = "FIXED_STAKE"
    MARTINGALE = "MARTINGALE"
    ANTI_MARTINGALE = "ANTI_MARTINGALE"
    PERCENTAGE = "PERCENTAGE"


@dataclass
class SniperSignal:
    direction: str  # "BUY" or "SELL"
    confidence: float  # 0.80+ required
    strategy_name: str  # Selected sub-strategy
    confirmations: int  # Number of confirmations
    entry_price: float
    risk_reward: float
    analysis: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "confidence": self.confidence,
            "strategy_name": self.strategy_name,
            "confirmations": self.confirmations,
            "entry_price": self.entry_price,
            "risk_reward": self.risk_reward,
            "analysis": self.analysis,
            "timestamp": self.timestamp
        }


class SniperStrategy:
    """
    Sniper Strategy - High probability only trading
    
    Features:
    - Ultra-selective entry filter (80%+ confidence only)
    - Multi-strategy chooser
    - Risk management integration
    - Money management options
    - Session statistics tracking
    """
    
    # Available sub-strategies
    STRATEGIES = [
        "RSI_EXTREME",
        "EMA_CROSSOVER",
        "MACD_DIVERGENCE",
        "SUPPORT_RESISTANCE",
        "TREND_CONTINUATION",
        "REVERSAL_PATTERN"
    ]
    
    # Thresholds - STRICT for high probability only
    MIN_CONFIDENCE = 0.80  # High probability requirement
    MIN_CONFIRMATIONS = 3  # Require multiple confirmations
    MIN_TICKS = 50  # Proper warmup for indicator accuracy
    
    def __init__(self, symbol: str = "R_100"):
        self.symbol = symbol
        self.indicators = TechnicalIndicators()
        self.ticks: deque = deque(maxlen=200)
        self.prices: List[float] = []
        
        # Strategy selection
        self.selected_strategy: Optional[str] = None
        
        # Dynamic thresholds based on volatility
        self.dynamic_thresholds = DynamicThresholds()
        self.use_dynamic_thresholds = True
        self.current_thresholds: Optional[Dict[str, float]] = None
        
        # Money management
        self.money_management = MoneyManagement.FIXED_STAKE
        self.base_stake = 1.0
        self.martingale_multiplier = 2.0
        self.max_martingale_level = 5
        self.current_level = 0
        self.percentage_risk = 2.0  # 2% of balance
        
        # Session tracking
        self.session_stats = {
            "wins": 0,
            "losses": 0,
            "profit": 0.0,
            "start_time": time.time(),
            "duration": 0
        }
        
        # Signal history
        self.signals: deque = deque(maxlen=100)
        self.last_signal_time = 0
        self.signal_cooldown = 20  # Ultra-selective - long cooldown between entries
        
        # Trading state - Default to True for automatic trading
        self.is_trading = True
        self.ping_ms = 0
    
    def add_tick(self, tick: Dict[str, Any]) -> Optional[SniperSignal]:
        """Add new tick data and analyze for signals"""
        self.ticks.append(tick)
        price = tick.get("quote", tick.get("price", 0))
        if price > 0:
            self.prices.append(price)
            if len(self.prices) > 200:
                self.prices = self.prices[-200:]
        
        # Analyze for trading signal (only when trading is enabled)
        if self.is_trading:
            return self.analyze()
        return None
    
    def set_strategy(self, strategy_name: str):
        """Set active sub-strategy"""
        if strategy_name in self.STRATEGIES:
            self.selected_strategy = strategy_name
            logger.info(f"Sniper strategy set to: {strategy_name}")
    
    def analyze(self) -> Optional[SniperSignal]:
        """
        Analyze for high-probability entry
        
        Only signals when confidence >= 80%
        """
        if len(self.prices) < self.MIN_TICKS:
            return None
        
        # Check cooldown
        if time.time() - self.last_signal_time < self.signal_cooldown:
            return None
        
        # Run all strategy checks
        results = []
        
        if self.selected_strategy:
            # Only run selected strategy
            result = self._run_strategy(self.selected_strategy)
            if result:
                results.append(result)
        else:
            # Run all strategies and pick best
            for strategy in self.STRATEGIES:
                result = self._run_strategy(strategy)
                if result:
                    results.append(result)
        
        if not results:
            return None
        
        # Pick highest confidence
        best = max(results, key=lambda x: x["confidence"])
        
        if best["confidence"] < self.MIN_CONFIDENCE:
            return None
        
        if best["confirmations"] < self.MIN_CONFIRMATIONS:
            return None
        
        signal = SniperSignal(
            direction=best["direction"],
            confidence=best["confidence"],
            strategy_name=best["strategy"],
            confirmations=best["confirmations"],
            entry_price=self.prices[-1],
            risk_reward=best.get("risk_reward", 1.5),
            analysis=best.get("analysis", {})
        )
        
        self.signals.append(signal)
        self.last_signal_time = time.time()
        
        logger.info(f"SNIPER Signal: {best['direction']} via {best['strategy']} @ {best['confidence']*100:.1f}%")
        
        return signal
    
    def _run_strategy(self, strategy_name: str) -> Optional[Dict]:
        """Run specific sub-strategy"""
        if strategy_name == "RSI_EXTREME":
            return self._rsi_extreme()
        elif strategy_name == "EMA_CROSSOVER":
            return self._ema_crossover()
        elif strategy_name == "MACD_DIVERGENCE":
            return self._macd_divergence()
        elif strategy_name == "SUPPORT_RESISTANCE":
            return self._support_resistance()
        elif strategy_name == "TREND_CONTINUATION":
            return self._trend_continuation()
        elif strategy_name == "REVERSAL_PATTERN":
            return self._reversal_pattern()
        return None
    
    def _get_dynamic_thresholds(self) -> Dict[str, float]:
        """Get current volatility-adjusted thresholds"""
        if len(self.prices) < 20:
            return {
                "rsi_extreme_low": 20,
                "rsi_extreme_high": 80,
                "stoch_extreme_low": 20,
                "stoch_extreme_high": 80
            }
        
        recent = self.prices[-20:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std_dev = math.sqrt(variance)
        volatility = (std_dev / mean) * 100 if mean > 0 else 1.0
        vol_percentile = min(100, max(0, volatility * 50))
        
        if self.use_dynamic_thresholds:
            self.current_thresholds = self.dynamic_thresholds.adjust_thresholds(vol_percentile)
            return {
                "rsi_extreme_low": max(15, self.current_thresholds["rsi_oversold_low"]),
                "rsi_extreme_high": min(85, self.current_thresholds["rsi_overbought_high"]),
                "stoch_extreme_low": max(15, self.current_thresholds["stoch_oversold"]),
                "stoch_extreme_high": min(85, self.current_thresholds["stoch_overbought"])
            }
        return {
            "rsi_extreme_low": 20,
            "rsi_extreme_high": 80,
            "stoch_extreme_low": 20,
            "stoch_extreme_high": 80
        }
    
    def _rsi_extreme(self) -> Optional[Dict]:
        """RSI Extreme strategy - oversold/overbought with dynamic thresholds"""
        rsi = self.indicators.calculate_rsi(self.prices, 14)
        if rsi is None:
            return None
        
        thresholds = self._get_dynamic_thresholds()
        rsi_low = thresholds["rsi_extreme_low"]
        rsi_high = thresholds["rsi_extreme_high"]
        
        confirmations = 0
        direction = None
        confidence = 0.5
        
        # Check RSI extreme with dynamic thresholds
        if rsi <= rsi_low:
            direction = "BUY"
            confidence = 0.70 + (rsi_low - rsi) * 0.01
            confirmations += 1
        elif rsi >= rsi_high:
            direction = "SELL"
            confidence = 0.70 + (rsi - rsi_high) * 0.01
            confirmations += 1
        else:
            return None
        
        # Confirm with EMA
        ema_9 = self.indicators.calculate_ema(self.prices, 9)
        ema_21 = self.indicators.calculate_ema(self.prices, 21)
        
        if ema_9 and ema_21:
            if direction == "BUY" and ema_9 > ema_21:
                confirmations += 1
                confidence += 0.05
            elif direction == "SELL" and ema_9 < ema_21:
                confirmations += 1
                confidence += 0.05
        
        # Confirm with Stochastic using dynamic thresholds
        stoch = self.indicators.calculate_stochastic(self.prices, 14)
        thresholds = self._get_dynamic_thresholds()
        if stoch is not None:
            if direction == "BUY" and stoch < thresholds["stoch_extreme_low"]:
                confirmations += 1
                confidence += 0.05
            elif direction == "SELL" and stoch > thresholds["stoch_extreme_high"]:
                confirmations += 1
                confidence += 0.05
        
        # ADX confirmation
        adx = self.indicators.calculate_adx(self.prices, 14)
        if adx and adx > 20:
            confirmations += 1
            confidence += 0.05
        
        return {
            "strategy": "RSI_EXTREME",
            "direction": direction,
            "confidence": min(confidence, 0.95),
            "confirmations": confirmations,
            "analysis": {"rsi": rsi, "stoch": stoch, "adx": adx}
        }
    
    def _ema_crossover(self) -> Optional[Dict]:
        """EMA Crossover strategy"""
        ema_9 = self.indicators.calculate_ema(self.prices, 9)
        ema_21 = self.indicators.calculate_ema(self.prices, 21)
        ema_50 = self.indicators.calculate_ema(self.prices, 50)
        
        if not all([ema_9, ema_21, ema_50]):
            return None
        
        confirmations = 0
        direction = None
        confidence = 0.5
        
        # Check crossover
        prev_prices = self.prices[-10:-1]
        prev_ema_9 = self.indicators.calculate_ema(prev_prices, 9)
        prev_ema_21 = self.indicators.calculate_ema(prev_prices, 21)
        
        if prev_ema_9 and prev_ema_21:
            # Bullish crossover
            if prev_ema_9 <= prev_ema_21 and ema_9 > ema_21:
                direction = "BUY"
                confirmations += 2
                confidence = 0.65
            # Bearish crossover
            elif prev_ema_9 >= prev_ema_21 and ema_9 < ema_21:
                direction = "SELL"
                confirmations += 2
                confidence = 0.65
            else:
                return None
        else:
            return None
        
        # Confirm with EMA 50 trend
        if direction == "BUY" and ema_21 > ema_50:
            confirmations += 1
            confidence += 0.10
        elif direction == "SELL" and ema_21 < ema_50:
            confirmations += 1
            confidence += 0.10
        
        # ADX trend strength
        adx = self.indicators.calculate_adx(self.prices, 14)
        if adx and adx > 25:
            confirmations += 1
            confidence += 0.10
        
        return {
            "strategy": "EMA_CROSSOVER",
            "direction": direction,
            "confidence": min(confidence, 0.95),
            "confirmations": confirmations,
            "analysis": {"ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50, "adx": adx}
        }
    
    def _macd_divergence(self) -> Optional[Dict]:
        """MACD Divergence strategy"""
        macd_result = self.indicators.calculate_macd(self.prices)
        if not macd_result:
            return None
        
        macd_line = macd_result.get("macd", 0)
        signal_line = macd_result.get("signal", 0)
        histogram = macd_result.get("histogram", 0)
        
        confirmations = 0
        direction = None
        confidence = 0.5
        
        # Check MACD crossover
        if macd_line > signal_line and histogram > 0:
            direction = "BUY"
            confirmations += 1
            confidence = 0.60
        elif macd_line < signal_line and histogram < 0:
            direction = "SELL"
            confirmations += 1
            confidence = 0.60
        else:
            return None
        
        # Histogram strength
        if abs(histogram) > 0.5:
            confirmations += 1
            confidence += 0.10
        
        # RSI confirmation
        rsi = self.indicators.calculate_rsi(self.prices, 14)
        if rsi:
            if direction == "BUY" and rsi < 50:
                confirmations += 1
                confidence += 0.10
            elif direction == "SELL" and rsi > 50:
                confirmations += 1
                confidence += 0.10
        
        # ADX confirmation
        adx = self.indicators.calculate_adx(self.prices, 14)
        if adx and adx > 20:
            confirmations += 1
            confidence += 0.05
        
        return {
            "strategy": "MACD_DIVERGENCE",
            "direction": direction,
            "confidence": min(confidence, 0.95),
            "confirmations": confirmations,
            "analysis": {"macd": macd_line, "signal": signal_line, "histogram": histogram}
        }
    
    def _support_resistance(self) -> Optional[Dict]:
        """Support/Resistance breakout strategy"""
        if len(self.prices) < 50:
            return None
        
        current = self.prices[-1]
        recent = self.prices[-50:]
        
        # Find support/resistance levels
        high = max(recent)
        low = min(recent)
        range_size = high - low
        
        if range_size == 0:
            return None
        
        # Check breakout
        confirmations = 0
        direction = None
        confidence = 0.5
        
        # Near resistance breakout
        if current > high * 0.998:
            direction = "BUY"
            confirmations += 2
            confidence = 0.65
        # Near support breakdown
        elif current < low * 1.002:
            direction = "SELL"
            confirmations += 2
            confidence = 0.65
        else:
            return None
        
        # Volume/momentum confirmation
        momentum = (current - recent[-5]) / recent[-5] * 100 if recent[-5] != 0 else 0
        if direction == "BUY" and momentum > 0.1:
            confirmations += 1
            confidence += 0.10
        elif direction == "SELL" and momentum < -0.1:
            confirmations += 1
            confidence += 0.10
        
        # ADX confirmation
        adx = self.indicators.calculate_adx(self.prices, 14)
        if adx and adx > 25:
            confirmations += 1
            confidence += 0.10
        
        return {
            "strategy": "SUPPORT_RESISTANCE",
            "direction": direction,
            "confidence": min(confidence, 0.95),
            "confirmations": confirmations,
            "analysis": {"high": high, "low": low, "current": current, "momentum": momentum}
        }
    
    def _trend_continuation(self) -> Optional[Dict]:
        """Trend continuation strategy"""
        ema_9 = self.indicators.calculate_ema(self.prices, 9)
        ema_21 = self.indicators.calculate_ema(self.prices, 21)
        ema_50 = self.indicators.calculate_ema(self.prices, 50)
        
        if not all([ema_9, ema_21, ema_50]):
            return None
        
        adx = self.indicators.calculate_adx(self.prices, 14)
        if not adx or adx < 25:
            return None  # Need strong trend
        
        confirmations = 0
        direction = None
        confidence = 0.5
        
        # Check trend alignment
        if ema_9 > ema_21 > ema_50:
            direction = "BUY"
            confirmations += 3
            confidence = 0.75
        elif ema_9 < ema_21 < ema_50:
            direction = "SELL"
            confirmations += 3
            confidence = 0.75
        else:
            return None
        
        # Strong ADX
        if adx > 30:
            confirmations += 1
            confidence += 0.10
        
        # RSI not extreme (healthy trend)
        rsi = self.indicators.calculate_rsi(self.prices, 14)
        if rsi:
            if direction == "BUY" and 40 < rsi < 70:
                confirmations += 1
                confidence += 0.05
            elif direction == "SELL" and 30 < rsi < 60:
                confirmations += 1
                confidence += 0.05
        
        return {
            "strategy": "TREND_CONTINUATION",
            "direction": direction,
            "confidence": min(confidence, 0.95),
            "confirmations": confirmations,
            "risk_reward": 2.0,
            "analysis": {"ema_9": ema_9, "ema_21": ema_21, "ema_50": ema_50, "adx": adx}
        }
    
    def _reversal_pattern(self) -> Optional[Dict]:
        """Reversal pattern detection with dynamic thresholds"""
        rsi = self.indicators.calculate_rsi(self.prices, 14)
        stoch = self.indicators.calculate_stochastic(self.prices, 14)
        
        if not all([rsi, stoch]):
            return None
        
        thresholds = self._get_dynamic_thresholds()
        rsi_low = thresholds["rsi_extreme_low"] + 5  # Slightly less extreme for reversal
        rsi_high = thresholds["rsi_extreme_high"] - 5
        stoch_low = thresholds["stoch_extreme_low"]
        stoch_high = thresholds["stoch_extreme_high"]
        
        confirmations = 0
        direction = None
        confidence = 0.5
        
        # Double bottom/top detection with dynamic thresholds
        if rsi < rsi_low and stoch < stoch_low:
            direction = "BUY"
            confirmations += 2
            confidence = 0.70
        elif rsi > rsi_high and stoch > stoch_high:
            direction = "SELL"
            confirmations += 2
            confidence = 0.70
        else:
            return None
        
        # MACD divergence confirmation
        macd_result = self.indicators.calculate_macd(self.prices)
        if macd_result:
            histogram = macd_result.get("histogram", 0)
            if direction == "BUY" and histogram > 0:
                confirmations += 1
                confidence += 0.10
            elif direction == "SELL" and histogram < 0:
                confirmations += 1
                confidence += 0.10
        
        # Price action confirmation
        current = self.prices[-1]
        prev_5 = self.prices[-6:-1]
        
        if direction == "BUY" and current > max(prev_5):
            confirmations += 1
            confidence += 0.05
        elif direction == "SELL" and current < min(prev_5):
            confirmations += 1
            confidence += 0.05
        
        return {
            "strategy": "REVERSAL_PATTERN",
            "direction": direction,
            "confidence": min(confidence, 0.95),
            "confirmations": confirmations,
            "risk_reward": 2.5,
            "analysis": {"rsi": rsi, "stoch": stoch}
        }
    
    def get_stake(self, balance: float = 1000) -> float:
        """Calculate stake based on money management"""
        if self.money_management == MoneyManagement.FIXED_STAKE:
            return self.base_stake
        
        elif self.money_management == MoneyManagement.MARTINGALE:
            return self.base_stake * (self.martingale_multiplier ** self.current_level)
        
        elif self.money_management == MoneyManagement.ANTI_MARTINGALE:
            wins = self.session_stats["wins"]
            if wins > 0:
                return self.base_stake * (1 + wins * 0.2)
            return self.base_stake
        
        elif self.money_management == MoneyManagement.PERCENTAGE:
            return balance * (self.percentage_risk / 100)
        
        return self.base_stake
    
    def record_result(self, won: bool, profit: float):
        """Record trade result"""
        if won:
            self.session_stats["wins"] += 1
            self.current_level = 0
        else:
            self.session_stats["losses"] += 1
            self.current_level = min(self.current_level + 1, self.max_martingale_level)
        
        self.session_stats["profit"] += profit
        self.session_stats["duration"] = time.time() - self.session_stats["start_time"]
    
    def set_money_management(self, mm_type: MoneyManagement, **kwargs):
        """Configure money management"""
        self.money_management = mm_type
        
        if "base_stake" in kwargs:
            self.base_stake = kwargs["base_stake"]
        if "multiplier" in kwargs:
            self.martingale_multiplier = kwargs["multiplier"]
        if "max_level" in kwargs:
            self.max_martingale_level = kwargs["max_level"]
        if "percentage" in kwargs:
            self.percentage_risk = kwargs["percentage"]
    
    def start_trading(self):
        """Start trading session"""
        self.is_trading = True
        self.session_stats = {
            "wins": 0,
            "losses": 0,
            "profit": 0.0,
            "start_time": time.time(),
            "duration": 0
        }
    
    def stop_trading(self):
        """Stop trading session"""
        self.is_trading = False
        self.session_stats["duration"] = time.time() - self.session_stats["start_time"]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get strategy statistics"""
        total = self.session_stats["wins"] + self.session_stats["losses"]
        win_rate = (self.session_stats["wins"] / total * 100) if total > 0 else 0
        
        return {
            "symbol": self.symbol,
            "ticks_count": len(self.ticks),
            "signals_count": len(self.signals),
            "selected_strategy": self.selected_strategy,
            "money_management": self.money_management.value,
            "is_trading": self.is_trading,
            "session_wins": self.session_stats["wins"],
            "session_losses": self.session_stats["losses"],
            "session_profit": self.session_stats["profit"],
            "win_rate": win_rate,
            "duration_seconds": self.session_stats["duration"],
            "current_level": self.current_level,
            "ping_ms": self.ping_ms
        }
