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
    
    # Thresholds by risk level - STRICT for quality signals
    CONFIDENCE_THRESHOLDS = {
        RiskLevel.LOW: 0.65,        # Conservative
        RiskLevel.MEDIUM: 0.55,     # Balanced
        RiskLevel.HIGH: 0.50,       # Moderate
        RiskLevel.AGGRESSIVE: 0.45  # Still requires confirmation
    }
    
    # Strategy-specific confidence overrides - STRICT for quality
    STRATEGY_CONFIDENCE_OVERRIDES = {
        "AMT": 0.55,          # Accumulator needs moderate confidence
        "SNIPER": 0.80,       # Sniper must be high probability
        "TERMINAL": 0.65,     # Terminal needs strong signals
        "TICK_PICKER": 0.60,  # Tick patterns need confirmation
        "DIGITPAD": 0.60,     # Digit patterns need confirmation  
        "LDP": 0.60,          # LDP needs statistical significance
        "MULTI_INDICATOR": 0.60  # Multi-indicator needs confluence
    }
    
    # Strategy-specific minimum cooldown (seconds) - PROPER INTERVALS
    STRATEGY_COOLDOWNS = {
        "AMT": 15,           # Accumulator needs time between entries
        "SNIPER": 20,        # Sniper is ultra-selective
        "TERMINAL": 12,      # Terminal needs analysis time
        "TICK_PICKER": 10,   # Tick picker moderate cooldown
        "DIGITPAD": 30,      # Digit needs sample collection
        "LDP": 30,           # LDP needs sample collection
        "MULTI_INDICATOR": 12,  # Multi-indicator moderate
        "DEFAULT": 10        # Default cooldown
    }
    
    MIN_ENTRY_SCORE = 55  # Require quality setups
    HIGH_ENTRY_SCORE = 80  # High quality threshold
    
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
        
        # 3. Trend alignment - STRICT CHECK WITH HARD BLOCK
        trend = market_data.get("trend", "NEUTRAL")
        adx = market_data.get("adx", 0)
        ema_fast = market_data.get("ema_fast", 0)
        ema_slow = market_data.get("ema_slow", 0)
        
        # HARD BLOCK: Counter-trend trades with strong ADX are immediately rejected
        is_counter_trend = (
            (direction == "BUY" and trend == "DOWNTREND") or
            (direction == "SELL" and trend == "UPTREND")
        )
        if is_counter_trend and adx >= 20:
            reasons.append(f"BLOCKED: Counter-trend {direction} vs {trend} with ADX {adx:.1f}")
            self.stats["blocked"] += 1
            self.stats["blocked_reasons"]["Counter-trend"] = \
                self.stats["blocked_reasons"].get("Counter-trend", 0) + 1
            return FilterResult(
                passed=False,
                score=0,
                risk_level=self.risk_level,
                reasons=reasons,
                adjustments={}
            )
        
        # Strong trend alignment
        if direction == "BUY" and trend == "UPTREND":
            scores["trend_alignment"] = 100
        elif direction == "SELL" and trend == "DOWNTREND":
            scores["trend_alignment"] = 100
        elif trend == "NEUTRAL" or trend == "RANGING":
            # Neutral is acceptable but not ideal
            scores["trend_alignment"] = 65
            reasons.append(f"Neutral trend - moderate confidence")
        else:
            # Counter-trend with weak ADX - heavily penalized but allowed
            scores["trend_alignment"] = 25
            reasons.append(f"Counter-trend trade: {direction} vs {trend} - HIGH RISK")
        
        # ADX trend strength check - STRICT
        if adx > 30:
            # Very strong trend - bonus for aligned, harsh penalty for counter
            if (direction == "BUY" and trend == "UPTREND") or (direction == "SELL" and trend == "DOWNTREND"):
                scores["trend_alignment"] = min(100, scores["trend_alignment"] + 15)
            elif trend not in ["NEUTRAL", "RANGING"]:
                scores["trend_alignment"] = max(0, scores["trend_alignment"] - 20)
                reasons.append(f"Strong opposing trend (ADX: {adx:.1f}) - AVOID")
        elif adx > 22:
            if (direction == "BUY" and trend == "UPTREND") or (direction == "SELL" and trend == "DOWNTREND"):
                scores["trend_alignment"] = min(100, scores["trend_alignment"] + 10)
        elif adx < 15:
            # Weak trend - reduce confidence
            scores["trend_alignment"] = max(0, scores["trend_alignment"] - 15)
            reasons.append(f"Weak trend strength (ADX: {adx:.1f})")
        
        # EMA alignment check if available
        if ema_fast and ema_slow:
            if direction == "BUY" and ema_fast < ema_slow:
                scores["trend_alignment"] = max(0, scores["trend_alignment"] - 15)
                reasons.append("EMA not aligned for BUY")
            elif direction == "SELL" and ema_fast > ema_slow:
                scores["trend_alignment"] = max(0, scores["trend_alignment"] - 15)
                reasons.append("EMA not aligned for SELL")
        
        # 4. Session time
        import time as time_module
        current_hour = time_module.gmtime().tm_hour
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
        
        # Determine if passed - STRICT CHECK, no marginal entries
        passed = total_score >= self.MIN_ENTRY_SCORE and confidence >= conf_threshold
        
        # Additional strict checks
        adjustments = {}
        
        # Counter-trend penalty - block if trend alignment is too low
        if scores.get("trend_alignment", 0) < 40:
            passed = False
            reasons.append("Blocked: Trend alignment too weak")
        
        # Volatility check - block extreme volatility
        if scores.get("volatility", 50) < 30:
            passed = False
            reasons.append("Blocked: Volatility conditions unfavorable")
        
        # High-quality setup bonus (only for truly excellent setups)
        if total_score >= self.HIGH_ENTRY_SCORE and confidence >= 0.75:
            adjustments["stake_increase"] = 1.15  # Modest 15% increase
            reasons.append("High-quality setup - slightly increased confidence")
        
        # Update stats and last signal time
        if passed:
            self.stats["passed"] += 1
            self.last_signal_time = time_module.time()
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
        
        # Changed to info level for better visibility
        logger.info(
            f"📋 Entry filter: {'✅ PASSED' if passed else '❌ BLOCKED'} "
            f"Score: {total_score:.1f}/{self.MIN_ENTRY_SCORE} | Confidence: {confidence:.2f}/{conf_threshold:.2f} | "
            f"Reasons: {', '.join(reasons) or 'All clear'}"
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
