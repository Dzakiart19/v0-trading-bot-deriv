"""
Entry Filter - Universal high-chance entry filter for all strategies
"""

import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    AGGRESSIVE = "AGGRESSIVE"

@dataclass
class FilterResult:
    """Entry filter result"""
    passed: bool
    score: float  # 0-100
    risk_level: RiskLevel
    reasons: list
    adjustments: Dict[str, Any]

class EntryFilter:
    """
    Universal Entry Filter
    
    Validates trading signals before execution with:
    - Confidence threshold filtering
    - Volatility checks
    - Trend alignment verification
    - Session time filtering
    - Entry score calculation
    - Strategy-specific thresholds
    """
    
    # Thresholds by risk level
    CONFIDENCE_THRESHOLDS = {
        RiskLevel.LOW: 0.65,
        RiskLevel.MEDIUM: 0.60,
        RiskLevel.HIGH: 0.55,
        RiskLevel.AGGRESSIVE: 0.50
    }
    
    # Strategy-specific confidence overrides (higher = stricter)
    STRATEGY_CONFIDENCE_OVERRIDES = {
        "AMT": 0.75,        # Accumulator needs higher confidence
        "SNIPER": 0.80,     # Sniper is ultra-selective
        "TERMINAL": 0.65,
        "TICK_PICKER": 0.60,
        "DIGITPAD": 0.60,
        "LDP": 0.60,
        "MULTI_INDICATOR": 0.60
    }
    
    # Strategy-specific minimum cooldown (seconds)
    STRATEGY_COOLDOWNS = {
        "AMT": 30,          # 30 seconds between AMT trades
        "SNIPER": 45,       # 45 seconds for sniper
        "DEFAULT": 10
    }
    
    MIN_ENTRY_SCORE = 55
    HIGH_ENTRY_SCORE = 80
    
    # Scoring weights
    WEIGHTS = {
        "confidence": 0.40,
        "volatility": 0.25,
        "trend_alignment": 0.20,
        "session_time": 0.15
    }
    
    # Session times (UTC hours)
    SESSIONS = {
        "asian": (0, 8),
        "european": (7, 16),
        "american": (13, 22)
    }
    
    def __init__(self, risk_level: RiskLevel = RiskLevel.MEDIUM, strategy_name: str = "DEFAULT"):
        self.risk_level = risk_level
        self.strategy_name = strategy_name
        self.stats = {
            "total_filtered": 0,
            "passed": 0,
            "blocked": 0,
            "blocked_reasons": {}
        }
        self.last_signal_time = 0
    
    def set_strategy(self, strategy_name: str):
        """Set strategy for strategy-specific filtering"""
        self.strategy_name = strategy_name
    
    def _get_confidence_threshold(self) -> float:
        """Get confidence threshold based on strategy and risk level"""
        # Check for strategy-specific override first
        if self.strategy_name in self.STRATEGY_CONFIDENCE_OVERRIDES:
            return self.STRATEGY_CONFIDENCE_OVERRIDES[self.strategy_name]
        return self.CONFIDENCE_THRESHOLDS[self.risk_level]
    
    def _check_cooldown(self) -> bool:
        """Check if cooldown period has passed"""
        import time
        cooldown = self.STRATEGY_COOLDOWNS.get(
            self.strategy_name, 
            self.STRATEGY_COOLDOWNS["DEFAULT"]
        )
        return time.time() - self.last_signal_time >= cooldown
    
    def filter(
        self,
        signal: Dict[str, Any],
        market_data: Dict[str, Any]
    ) -> FilterResult:
        """
        Filter a trading signal
        
        Args:
            signal: Signal data with confidence, direction, etc.
            market_data: Current market data with volatility, trend, etc.
            
        Returns:
            FilterResult with pass/fail and score
        """
        self.stats["total_filtered"] += 1
        
        reasons = []
        scores = {}
        
        confidence = signal.get("confidence", 0)
        direction = signal.get("direction", "HOLD")
        
        # Check cooldown first
        if not self._check_cooldown():
            reasons.append("In cooldown period")
            return FilterResult(
                passed=False,
                score=0,
                risk_level=self.risk_level,
                reasons=reasons,
                adjustments={}
            )
        
        # 1. Confidence check (with strategy-specific threshold)
        conf_threshold = self._get_confidence_threshold()
        if confidence >= conf_threshold:
            scores["confidence"] = min(100, (confidence / conf_threshold) * 100)
        else:
            scores["confidence"] = (confidence / conf_threshold) * 100
            reasons.append(f"Low confidence: {confidence:.2f} < {conf_threshold}")
        
        # 2. Volatility check
        volatility = market_data.get("volatility_percentile", 50)
        if volatility > 90:
            scores["volatility"] = 20
            reasons.append(f"Extreme volatility: {volatility:.1f}%")
        elif volatility > 75:
            scores["volatility"] = 50
            reasons.append(f"High volatility: {volatility:.1f}%")
        elif volatility < 10:
            scores["volatility"] = 60
            reasons.append(f"Very low volatility: {volatility:.1f}%")
        else:
            scores["volatility"] = 100 - abs(volatility - 50)
        
        # 3. Trend alignment
        trend = market_data.get("trend", "NEUTRAL")
        adx = market_data.get("adx", 0)
        
        if direction == "BUY" and trend == "UPTREND":
            scores["trend_alignment"] = 100
        elif direction == "SELL" and trend == "DOWNTREND":
            scores["trend_alignment"] = 100
        elif trend == "NEUTRAL" or trend == "RANGING":
            scores["trend_alignment"] = 70
        else:
            scores["trend_alignment"] = 40
            reasons.append(f"Counter-trend trade: {direction} vs {trend}")
        
        # ADX bonus/penalty
        if adx > 25:
            scores["trend_alignment"] = min(100, scores["trend_alignment"] + 10)
        elif adx < 15:
            scores["trend_alignment"] = max(0, scores["trend_alignment"] - 10)
        
        # 4. Session time
        current_hour = time.gmtime().tm_hour
        active_sessions = []
        
        for session, (start, end) in self.SESSIONS.items():
            if start <= current_hour <= end:
                active_sessions.append(session)
        
        if active_sessions:
            scores["session_time"] = 100
        else:
            scores["session_time"] = 60
            reasons.append("Outside major trading sessions")
        
        # Calculate weighted score
        total_score = sum(
            scores[key] * self.WEIGHTS[key]
            for key in scores
        )
        
        # Determine if passed
        passed = total_score >= self.MIN_ENTRY_SCORE and confidence >= conf_threshold
        
        # Adjustments for marginal cases
        adjustments = {}
        if total_score >= self.MIN_ENTRY_SCORE - 10 and total_score < self.MIN_ENTRY_SCORE:
            adjustments["stake_reduction"] = 0.5  # Reduce stake by 50%
            passed = True
            reasons.append("Marginal entry - reduced stake recommended")
        
        if total_score >= self.HIGH_ENTRY_SCORE:
            adjustments["stake_increase"] = 1.2  # Increase stake by 20%
            reasons.append("High-quality setup")
        
        # Update stats and last signal time
        if passed:
            self.stats["passed"] += 1
            import time
            self.last_signal_time = time.time()
        else:
            self.stats["blocked"] += 1
            for reason in reasons:
                key = reason.split(":")[0]
                self.stats["blocked_reasons"][key] = \
                    self.stats["blocked_reasons"].get(key, 0) + 1
        
        result = FilterResult(
            passed=passed,
            score=total_score,
            risk_level=self.risk_level,
            reasons=reasons,
            adjustments=adjustments
        )
        
        logger.debug(
            f"Entry filter: {'PASSED' if passed else 'BLOCKED'} "
            f"Score: {total_score:.1f} | Reasons: {', '.join(reasons) or 'None'}"
        )
        
        return result
    
    def get_market_context(self, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build market context from indicator data
        
        Args:
            indicators: Dict with RSI, ADX, ATR, etc.
            
        Returns:
            Market context dict for filtering
        """
        adx = indicators.get("adx", 0)
        plus_di = indicators.get("plus_di", 0)
        minus_di = indicators.get("minus_di", 0)
        vol_percentile = indicators.get("volatility_percentile", 50)
        regime = indicators.get("regime", "UNKNOWN")
        
        # Determine trend
        if adx > 25:
            if plus_di > minus_di:
                trend = "UPTREND"
            else:
                trend = "DOWNTREND"
        elif adx < 15:
            trend = "RANGING"
        else:
            trend = "NEUTRAL"
        
        return {
            "trend": trend,
            "adx": adx,
            "volatility_percentile": vol_percentile,
            "regime": regime
        }
    
    def set_risk_level(self, level: RiskLevel):
        """Update risk level"""
        self.risk_level = level
        logger.info(f"Entry filter risk level set to: {level.value}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get filter statistics"""
        total = self.stats["total_filtered"]
        if total == 0:
            return {"total": 0, "pass_rate": 0}
        
        return {
            "total": total,
            "passed": self.stats["passed"],
            "blocked": self.stats["blocked"],
            "pass_rate": self.stats["passed"] / total * 100,
            "blocked_reasons": self.stats["blocked_reasons"]
        }
    
    def reset_stats(self):
        """Reset filter statistics"""
        self.stats = {
            "total_filtered": 0,
            "passed": 0,
            "blocked": 0,
            "blocked_reasons": {}
        }
