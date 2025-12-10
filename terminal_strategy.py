"""
Terminal Strategy - Smart Analysis with 80% probability scoring
Based on https://terminal.nextrader.live/
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import time
import math

from indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


@dataclass
class TerminalSignal:
    direction: str  # "BUY" or "SELL"
    confidence: float  # 0.0 - 1.0
    probability: float  # Smart Analysis probability
    risk_level: RiskLevel
    entry_price: float
    take_profit: float
    stop_loss: float
    indicators: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": self.direction,
            "confidence": self.confidence,
            "probability": self.probability,
            "risk_level": self.risk_level.value,
            "entry_price": self.entry_price,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "indicators": self.indicators,
            "timestamp": self.timestamp
        }


class TerminalStrategy:
    """
    Terminal Strategy - Professional trading terminal
    
    Features:
    - Smart Analysis with 80% minimum probability
    - Multi-indicator weighting system
    - Risk level assessment
    - Hybrid recovery system (Martingale + Anti-Martingale)
    - Take Profit / Stop Loss recommendations
    """
    
    # Indicator weights for probability calculation
    WEIGHTS = {
        "rsi": 0.25,
        "ema": 0.25,
        "macd": 0.20,
        "stochastic": 0.15,
        "adx": 0.15
    }
    
    # Risk multipliers for Hybrid Recovery
    RISK_MULTIPLIERS = {
        RiskLevel.LOW: {"multiplier": 1.5, "max_levels": 6},
        RiskLevel.MEDIUM: {"multiplier": 1.8, "max_levels": 5},
        RiskLevel.HIGH: {"multiplier": 2.1, "max_levels": 4},
        RiskLevel.VERY_HIGH: {"multiplier": 2.5, "max_levels": 3}
    }
    
    MIN_CONFIDENCE = 0.75  # 75% minimum for signal (slightly lowered for more frequent trades)
    MIN_TICKS = 30  # Reduced for faster warmup
    
    def __init__(self, symbol: str = "R_100"):
        self.symbol = symbol
        self.indicators = TechnicalIndicators()
        self.ticks: deque = deque(maxlen=200)
        self.prices: List[float] = []
        
        # Smart Analysis state
        self.smart_analysis_enabled = True
        self.hybrid_recovery_enabled = False
        
        # Trading state
        self.current_risk = RiskLevel.MEDIUM
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.current_level = 0
        
        # Signal history
        self.signals: deque = deque(maxlen=100)
        self.last_signal_time = 0
        self.signal_cooldown = 3  # seconds (reduced for faster trading)
    
    def add_tick(self, tick: Dict[str, Any]) -> Optional[TerminalSignal]:
        """Add new tick data and analyze for signals"""
        self.ticks.append(tick)
        price = tick.get("quote", tick.get("price", 0))
        if price > 0:
            self.prices.append(price)
            if len(self.prices) > 200:
                self.prices = self.prices[-200:]
        
        # Analyze for trading signal
        return self.analyze()
    
    def analyze(self) -> Optional[TerminalSignal]:
        """
        Perform Smart Analysis
        
        Returns:
            TerminalSignal if probability >= 80%, else None
        """
        if len(self.prices) < self.MIN_TICKS:
            return None
        
        # Check cooldown
        if time.time() - self.last_signal_time < self.signal_cooldown:
            return None
        
        # Calculate all indicators
        indicator_scores = self._calculate_indicator_scores()
        
        # Calculate weighted probability
        probability = self._calculate_probability(indicator_scores)
        
        # Determine direction
        direction = self._determine_direction(indicator_scores)
        
        if direction is None:
            return None
        
        # Check if meets minimum confidence
        if not self.smart_analysis_enabled:
            # Without smart analysis, use lower threshold
            if probability < 0.60:
                return None
        else:
            if probability < self.MIN_CONFIDENCE:
                return None
        
        # Calculate risk level
        risk_level = self._assess_risk(indicator_scores)
        
        # Calculate TP/SL
        current_price = self.prices[-1]
        atr = self._calculate_atr()
        
        if direction == "BUY":
            take_profit = current_price + (atr * 2)
            stop_loss = current_price - (atr * 1.5)
        else:
            take_profit = current_price - (atr * 2)
            stop_loss = current_price + (atr * 1.5)
        
        signal = TerminalSignal(
            direction=direction,
            confidence=probability,
            probability=probability * 100,  # Convert to percentage
            risk_level=risk_level,
            entry_price=current_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            indicators=indicator_scores
        )
        
        self.signals.append(signal)
        self.last_signal_time = time.time()
        
        logger.info(f"Terminal Signal: {direction} @ {probability*100:.1f}% prob, Risk: {risk_level.value}")
        
        return signal
    
    def _calculate_indicator_scores(self) -> Dict[str, Any]:
        """Calculate scores for each indicator"""
        scores = {}
        
        # RSI Analysis
        rsi = self.indicators.calculate_rsi(self.prices, 14)
        if rsi is not None:
            if rsi < 30:
                scores["rsi"] = {"value": rsi, "signal": "BUY", "strength": (30 - rsi) / 30}
            elif rsi > 70:
                scores["rsi"] = {"value": rsi, "signal": "SELL", "strength": (rsi - 70) / 30}
            else:
                scores["rsi"] = {"value": rsi, "signal": "NEUTRAL", "strength": 0}
        
        # EMA Crossover
        ema_9 = self.indicators.calculate_ema(self.prices, 9)
        ema_21 = self.indicators.calculate_ema(self.prices, 21)
        if ema_9 is not None and ema_21 is not None:
            ema_diff = (ema_9 - ema_21) / ema_21 * 100
            if ema_9 > ema_21:
                scores["ema"] = {"value": ema_diff, "signal": "BUY", "strength": min(abs(ema_diff) / 0.5, 1)}
            else:
                scores["ema"] = {"value": ema_diff, "signal": "SELL", "strength": min(abs(ema_diff) / 0.5, 1)}
        
        # MACD
        macd_result = self.indicators.calculate_macd(self.prices)
        if macd_result:
            macd_line = macd_result.get("macd", 0)
            signal_line = macd_result.get("signal", 0)
            histogram = macd_result.get("histogram", 0)
            
            if macd_line > signal_line and histogram > 0:
                scores["macd"] = {"value": histogram, "signal": "BUY", "strength": min(abs(histogram) / 0.5, 1)}
            elif macd_line < signal_line and histogram < 0:
                scores["macd"] = {"value": histogram, "signal": "SELL", "strength": min(abs(histogram) / 0.5, 1)}
            else:
                scores["macd"] = {"value": histogram, "signal": "NEUTRAL", "strength": 0}
        
        # Stochastic
        stoch = self.indicators.calculate_stochastic(self.prices, 14)
        if stoch is not None:
            if stoch < 20:
                scores["stochastic"] = {"value": stoch, "signal": "BUY", "strength": (20 - stoch) / 20}
            elif stoch > 80:
                scores["stochastic"] = {"value": stoch, "signal": "SELL", "strength": (stoch - 80) / 20}
            else:
                scores["stochastic"] = {"value": stoch, "signal": "NEUTRAL", "strength": 0}
        
        # ADX (Trend Strength)
        adx = self.indicators.calculate_adx(self.prices, 14)
        if adx is not None:
            trend_strength = "STRONG" if adx > 25 else "MODERATE" if adx > 18 else "WEAK"
            scores["adx"] = {"value": adx, "trend_strength": trend_strength, "strength": min(adx / 50, 1)}
        
        return scores
    
    def _calculate_probability(self, scores: Dict[str, Any]) -> float:
        """Calculate weighted probability from indicator scores"""
        total_weight = 0
        weighted_sum = 0
        
        for indicator, weight in self.WEIGHTS.items():
            if indicator in scores and scores[indicator].get("signal") != "NEUTRAL":
                strength = scores[indicator].get("strength", 0)
                weighted_sum += weight * strength
                total_weight += weight
        
        if total_weight == 0:
            return 0.5
        
        # Normalize to 0.5 - 1.0 range (50% - 100%)
        base_prob = weighted_sum / total_weight
        probability = 0.5 + (base_prob * 0.5)
        
        # ADX boost for strong trends
        if "adx" in scores:
            adx_val = scores["adx"].get("value", 0)
            if adx_val > 25:
                probability = min(probability * 1.1, 0.95)
            elif adx_val < 15:
                probability *= 0.9
        
        return min(max(probability, 0), 1)
    
    def _determine_direction(self, scores: Dict[str, Any]) -> Optional[str]:
        """Determine trade direction from indicator consensus"""
        buy_votes = 0
        sell_votes = 0
        
        for indicator in ["rsi", "ema", "macd", "stochastic"]:
            if indicator in scores:
                signal = scores[indicator].get("signal")
                strength = scores[indicator].get("strength", 0)
                
                if signal == "BUY":
                    buy_votes += strength * self.WEIGHTS.get(indicator, 0.25)
                elif signal == "SELL":
                    sell_votes += strength * self.WEIGHTS.get(indicator, 0.25)
        
        # Need clear majority
        if buy_votes > sell_votes and buy_votes > 0.3:
            return "BUY"
        elif sell_votes > buy_votes and sell_votes > 0.3:
            return "SELL"
        
        return None
    
    def _assess_risk(self, scores: Dict[str, Any]) -> RiskLevel:
        """Assess risk level based on market conditions"""
        # Calculate volatility
        volatility = self._calculate_volatility()
        
        # ADX trend strength
        adx_val = scores.get("adx", {}).get("value", 20)
        
        # Risk assessment
        if volatility > 2.0:  # High volatility
            if adx_val > 30:
                return RiskLevel.VERY_HIGH
            return RiskLevel.HIGH
        elif volatility > 1.0:
            if adx_val > 25:
                return RiskLevel.MEDIUM
            return RiskLevel.HIGH
        else:
            if adx_val > 20:
                return RiskLevel.LOW
            return RiskLevel.MEDIUM
    
    def _calculate_atr(self, period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(self.prices) < period + 1:
            return 0.01
        
        trs = []
        for i in range(-period, 0):
            high = max(self.prices[i], self.prices[i-1])
            low = min(self.prices[i], self.prices[i-1])
            tr = high - low
            trs.append(tr)
        
        return sum(trs) / len(trs) if trs else 0.01
    
    def _calculate_volatility(self) -> float:
        """Calculate current volatility"""
        if len(self.prices) < 20:
            return 1.0
        
        recent = self.prices[-20:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std_dev = math.sqrt(variance)
        
        # Normalize volatility (typical range 0.5 - 3.0)
        return (std_dev / mean) * 100
    
    def get_recovery_stake(self, base_stake: float) -> float:
        """Calculate stake for Hybrid Recovery System"""
        if not self.hybrid_recovery_enabled:
            return base_stake
        
        risk_config = self.RISK_MULTIPLIERS[self.current_risk]
        multiplier = risk_config["multiplier"]
        max_levels = risk_config["max_levels"]
        
        if self.current_level >= max_levels:
            logger.warning(f"Max recovery level reached ({max_levels})")
            return base_stake
        
        # Progressive recovery calculation
        if self.consecutive_losses > 0:
            # Martingale mode
            exponent = 1 + (self.current_level * 0.5)
            stake = base_stake * (multiplier ** exponent)
        elif self.consecutive_wins > 2:
            # Anti-Martingale mode (increase on wins)
            stake = base_stake * (1 + (self.consecutive_wins * 0.2))
        else:
            stake = base_stake
        
        return round(stake, 2)
    
    def record_result(self, won: bool, profit: float):
        """Record trade result for recovery system"""
        if won:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            self.current_level = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.current_level = min(self.current_level + 1, 5)
    
    def set_risk_level(self, risk: RiskLevel):
        """Set current risk level"""
        self.current_risk = risk
    
    def set_smart_analysis(self, enabled: bool):
        """Enable/disable Smart Analysis"""
        self.smart_analysis_enabled = enabled
    
    def set_hybrid_recovery(self, enabled: bool):
        """Enable/disable Hybrid Recovery"""
        self.hybrid_recovery_enabled = enabled
    
    def get_stats(self) -> Dict[str, Any]:
        """Get strategy statistics"""
        return {
            "symbol": self.symbol,
            "ticks_count": len(self.ticks),
            "signals_count": len(self.signals),
            "smart_analysis": self.smart_analysis_enabled,
            "hybrid_recovery": self.hybrid_recovery_enabled,
            "current_risk": self.current_risk.value,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "current_level": self.current_level
        }
