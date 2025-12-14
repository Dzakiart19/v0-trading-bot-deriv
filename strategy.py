"""
Multi-Indicator Strategy - Main trading strategy with RSI, EMA, MACD, Stochastic, ADX
"""

import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from collections import deque

from indicators import (
    calculate_rsi, calculate_ema, calculate_macd,
    calculate_stochastic, calculate_adx, calculate_atr,
    calculate_hma, calculate_zscore, detect_regime,
    calculate_volatility_percentile, safe_float
)

logger = logging.getLogger(__name__)

@dataclass
class Signal:
    """Trading signal with metadata"""
    direction: str  # "BUY", "SELL", or "HOLD"
    confidence: float  # 0.0 to 1.0
    confluence: float  # 0 to 100
    reason: str
    indicators: Dict[str, Any]
    timestamp: float
    symbol: str

class DynamicThresholds:
    """
    Dynamic threshold adjustment based on ATR volatility percentile.
    Widens thresholds in high volatility, tightens in low volatility.
    """
    
    def __init__(self):
        self.base_rsi_oversold_low = 15
        self.base_rsi_oversold_high = 28
        self.base_rsi_overbought_low = 72
        self.base_rsi_overbought_high = 85
        self.base_stoch_oversold = 20
        self.base_stoch_overbought = 80
        self.base_adx_strong = 25
    
    def adjust_thresholds(self, volatility_percentile: float) -> dict:
        """
        Adjust thresholds based on volatility percentile (0-100).
        High volatility (>70): Widen zones for safer entry
        Low volatility (<30): Tighten zones for faster entry
        """
        if volatility_percentile > 70:
            vol_factor = 1.15 + ((volatility_percentile - 70) / 100)
        elif volatility_percentile < 30:
            vol_factor = 0.90 - ((30 - volatility_percentile) / 150)
        else:
            vol_factor = 1.0
        
        vol_factor = max(0.80, min(1.30, vol_factor))
        
        rsi_expansion = (vol_factor - 1.0) * 10
        
        return {
            "rsi_oversold_low": max(10, self.base_rsi_oversold_low - rsi_expansion),
            "rsi_oversold_high": max(20, self.base_rsi_oversold_high - rsi_expansion),
            "rsi_overbought_low": min(80, self.base_rsi_overbought_low + rsi_expansion),
            "rsi_overbought_high": min(90, self.base_rsi_overbought_high + rsi_expansion),
            "stoch_oversold": max(15, self.base_stoch_oversold - rsi_expansion),
            "stoch_overbought": min(85, self.base_stoch_overbought + rsi_expansion),
            "adx_strong": max(20, self.base_adx_strong - (vol_factor - 1.0) * 5),
            "volatility_factor": vol_factor,
            "volatility_percentile": volatility_percentile
        }


class MultiIndicatorStrategy:
    """
    Enhanced Multi-Indicator Strategy v4.5
    
    Features:
    - RSI (14 period): 22-30 for BUY, 70-78 for SELL
    - EMA Crossover: 9/21 periods for trend confirmation
    - MACD (12/26/9): Momentum detection
    - Stochastic (14 period): Overbought/Oversold confirmation
    - ADX (14 period): Trend strength
    - ATR (14 period): Volatility measurement
    - Multi-Horizon Tick Direction Prediction
    - Regime Detection: TRENDING, RANGING, TRANSITIONAL
    - Mean Reversion Detection via Z-Score
    - Confluence Scoring (0-100)
    - DYNAMIC THRESHOLDS: ATR-based threshold adjustment
    """
    
    # Configuration - STRICT THRESHOLDS for quality signals
    RSI_PERIOD = 14
    RSI_OVERSOLD_LOW = 15      # Extreme oversold
    RSI_OVERSOLD_HIGH = 28     # Tight oversold zone
    RSI_OVERBOUGHT_LOW = 72    # Tight overbought zone
    RSI_OVERBOUGHT_HIGH = 85   # Extreme overbought
    
    EMA_FAST = 9
    EMA_SLOW = 21
    EMA_TREND = 50             # Added for trend confirmation
    
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    
    STOCH_PERIOD = 14
    STOCH_OVERSOLD = 20        # Strict oversold
    STOCH_OVERBOUGHT = 80      # Strict overbought
    
    ADX_PERIOD = 14
    ADX_STRONG = 25            # Strong trend threshold
    ADX_MODERATE = 20          # Moderate trend
    ADX_WEAK = 15              # Weak trend
    
    ATR_PERIOD = 14
    
    MIN_CONFLUENCE = 45        # Require strong confluence
    MIN_CONFIDENCE = 0.60      # Require moderate confidence
    SIGNAL_COOLDOWN = 10       # 10 seconds between signals
    
    def __init__(self, symbol: str = "R_100"):
        self.symbol = symbol
        self.tick_history: deque = deque(maxlen=200)
        self.last_signal_time = 0
        self.last_signal: Optional[Signal] = None
        
        # Configurable thresholds (can be modified for strategies like Sniper)
        self.min_confidence = self.MIN_CONFIDENCE
        self.min_confluence = self.MIN_CONFLUENCE
        
        # Dynamic thresholds based on volatility
        self.dynamic_thresholds = DynamicThresholds()
        self.use_dynamic_thresholds = True  # Enable by default
        self.current_thresholds: Optional[dict] = None
        
        # For high/low simulation from tick data
        self.highs: deque = deque(maxlen=200)
        self.lows: deque = deque(maxlen=200)
        self.closes: deque = deque(maxlen=200)
    
    def add_tick(self, tick: Dict[str, Any]) -> Optional[Signal]:
        """
        Add new tick data and analyze for signals
        
        Args:
            tick: Dict with 'quote' and 'epoch' keys
            
        Returns:
            Signal if conditions met, None otherwise
        """
        quote = safe_float(tick.get("quote", 0))
        if quote <= 0:
            return None
        
        self.tick_history.append(tick)
        
        # Simulate OHLC from ticks
        self.closes.append(quote)
        
        # For simplicity, use quote as high/low with small variance
        if len(self.closes) >= 2:
            prev = self.closes[-2]
            self.highs.append(max(quote, prev))
            self.lows.append(min(quote, prev))
        else:
            self.highs.append(quote)
            self.lows.append(quote)
        
        # Check cooldown
        current_time = time.time()
        if current_time - self.last_signal_time < self.SIGNAL_COOLDOWN:
            return None
        
        # Need enough data
        if len(self.closes) < 50:
            return None
        
        return self._analyze()
    
    def _analyze(self) -> Optional[Signal]:
        """Perform full analysis and generate signal"""
        prices = list(self.closes)
        highs = list(self.highs)
        lows = list(self.lows)
        
        # Calculate indicators
        rsi = calculate_rsi(prices, self.RSI_PERIOD)
        ema_fast = calculate_ema(prices, self.EMA_FAST)
        ema_slow = calculate_ema(prices, self.EMA_SLOW)
        macd_line, signal_line, histogram = calculate_macd(
            prices, self.MACD_FAST, self.MACD_SLOW, self.MACD_SIGNAL
        )
        stoch_k, stoch_d = calculate_stochastic(
            highs, lows, prices, self.STOCH_PERIOD
        )
        adx, plus_di, minus_di = calculate_adx(
            highs, lows, prices, self.ADX_PERIOD
        )
        atr = calculate_atr(highs, lows, prices, self.ATR_PERIOD)
        zscore = calculate_zscore(prices, 20)
        
        # Check if we have all indicators
        if not all([rsi, ema_fast, ema_slow, stoch_k, adx]):
            return None
        
        # Get current values
        current_rsi = rsi[-1] if rsi else 50
        current_ema_fast = ema_fast[-1] if ema_fast else 0
        current_ema_slow = ema_slow[-1] if ema_slow else 0
        current_macd = macd_line[-1] if macd_line else 0
        current_signal = signal_line[-1] if signal_line else 0
        current_histogram = histogram[-1] if histogram else 0
        current_stoch_k = stoch_k[-1] if stoch_k else 50
        current_stoch_d = stoch_d[-1] if stoch_d else 50
        current_adx = adx[-1] if adx else 0
        current_plus_di = plus_di[-1] if plus_di else 0
        current_minus_di = minus_di[-1] if minus_di else 0
        current_atr = atr[-1] if atr else 0
        current_zscore = zscore[-1] if zscore else 0
        
        # Detect market regime
        regime = detect_regime(adx, atr, prices)
        
        # Calculate volatility percentile
        vol_percentile = calculate_volatility_percentile(atr)
        
        # Apply dynamic thresholds based on volatility
        if self.use_dynamic_thresholds:
            self.current_thresholds = self.dynamic_thresholds.adjust_thresholds(vol_percentile)
            rsi_oversold_low = self.current_thresholds["rsi_oversold_low"]
            rsi_oversold_high = self.current_thresholds["rsi_oversold_high"]
            rsi_overbought_low = self.current_thresholds["rsi_overbought_low"]
            rsi_overbought_high = self.current_thresholds["rsi_overbought_high"]
            stoch_oversold = self.current_thresholds["stoch_oversold"]
            stoch_overbought = self.current_thresholds["stoch_overbought"]
            adx_strong = self.current_thresholds["adx_strong"]
        else:
            rsi_oversold_low = self.RSI_OVERSOLD_LOW
            rsi_oversold_high = self.RSI_OVERSOLD_HIGH
            rsi_overbought_low = self.RSI_OVERBOUGHT_LOW
            rsi_overbought_high = self.RSI_OVERBOUGHT_HIGH
            stoch_oversold = self.STOCH_OVERSOLD
            stoch_overbought = self.STOCH_OVERBOUGHT
            adx_strong = self.ADX_STRONG
        
        # Confluence scoring
        confluence = 0
        direction_votes = {"BUY": 0, "SELL": 0}
        reasons = []
        
        # Calculate EMA trend for validation
        ema_trend = calculate_ema(prices, 50) if len(prices) >= 50 else None
        current_ema_trend = ema_trend[-1] if ema_trend else 0
        is_uptrend = current_ema_fast > current_ema_slow > current_ema_trend if current_ema_trend else current_ema_fast > current_ema_slow
        is_downtrend = current_ema_fast < current_ema_slow < current_ema_trend if current_ema_trend else current_ema_fast < current_ema_slow
        
        # RSI Analysis (25 points max) - DYNAMIC ZONES
        if rsi_oversold_low <= current_rsi <= rsi_oversold_high:
            # Only count if EMA supports the direction
            if is_uptrend or current_ema_fast > current_ema_slow:
                confluence += 25
                direction_votes["BUY"] += 2
                reasons.append(f"RSI oversold ({current_rsi:.1f}) with EMA support")
            else:
                confluence += 15  # Reduced score without EMA confirmation
                direction_votes["BUY"] += 1
                reasons.append(f"RSI oversold ({current_rsi:.1f}) - needs EMA confirmation")
        elif rsi_overbought_low <= current_rsi <= rsi_overbought_high:
            if is_downtrend or current_ema_fast < current_ema_slow:
                confluence += 25
                direction_votes["SELL"] += 2
                reasons.append(f"RSI overbought ({current_rsi:.1f}) with EMA support")
            else:
                confluence += 15
                direction_votes["SELL"] += 1
                reasons.append(f"RSI overbought ({current_rsi:.1f}) - needs EMA confirmation")
        
        # EMA Crossover (20 points max)
        ema_diff = current_ema_fast - current_ema_slow
        if len(ema_fast) >= 2 and len(ema_slow) >= 2:
            prev_diff = ema_fast[-2] - ema_slow[-2]
            
            if prev_diff < 0 and ema_diff > 0:  # Bullish crossover
                confluence += 20
                direction_votes["BUY"] += 2
                reasons.append("EMA bullish crossover")
            elif prev_diff > 0 and ema_diff < 0:  # Bearish crossover
                confluence += 20
                direction_votes["SELL"] += 2
                reasons.append("EMA bearish crossover")
            elif ema_diff > 0:
                confluence += 10
                direction_votes["BUY"] += 1
            elif ema_diff < 0:
                confluence += 10
                direction_votes["SELL"] += 1
        
        # MACD Analysis (15 points max)
        if current_histogram > 0 and current_macd > current_signal:
            confluence += 15
            direction_votes["BUY"] += 1
            reasons.append("MACD bullish")
        elif current_histogram < 0 and current_macd < current_signal:
            confluence += 15
            direction_votes["SELL"] += 1
            reasons.append("MACD bearish")
        
        # Stochastic Analysis (15 points max) - DYNAMIC ZONES
        if current_stoch_k < stoch_oversold:
            confluence += 15
            direction_votes["BUY"] += 1
            reasons.append(f"Stoch oversold ({current_stoch_k:.1f})")
        elif current_stoch_k > stoch_overbought:
            confluence += 15
            direction_votes["SELL"] += 1
            reasons.append(f"Stoch overbought ({current_stoch_k:.1f})")
        
        # ADX/DMI Analysis (15 points max) - DYNAMIC THRESHOLD
        if current_adx >= adx_strong:
            confluence += 15
            if current_plus_di > current_minus_di:
                direction_votes["BUY"] += 1
                reasons.append(f"Strong uptrend (ADX: {current_adx:.1f})")
            else:
                direction_votes["SELL"] += 1
                reasons.append(f"Strong downtrend (ADX: {current_adx:.1f})")
        elif current_adx >= self.ADX_MODERATE:
            confluence += 10
        
        # ADX Directional Conflict Check
        di_diff = abs(current_plus_di - current_minus_di)
        if di_diff > 15:
            # Clear directional bias
            pass
        else:
            # Conflicting signals, reduce confluence
            confluence = max(0, confluence - 10)
        
        # Mean Reversion (Z-Score) (10 points max) - ONLY with trend confirmation
        # Mean reversion against strong trend is dangerous
        if current_zscore < -2.5:
            # Only count if not against strong downtrend
            if not is_downtrend or current_adx < self.ADX_MODERATE:
                confluence += 10
                direction_votes["BUY"] += 1
                reasons.append(f"Mean reversion BUY (Z: {current_zscore:.2f})")
            else:
                reasons.append(f"Mean reversion ignored - against trend (Z: {current_zscore:.2f})")
        elif current_zscore > 2.5:
            if not is_uptrend or current_adx < self.ADX_MODERATE:
                confluence += 10
                direction_votes["SELL"] += 1
                reasons.append(f"Mean reversion SELL (Z: {current_zscore:.2f})")
            else:
                reasons.append(f"Mean reversion ignored - against trend (Z: {current_zscore:.2f})")
        
        # Determine direction - require clear majority
        vote_diff = abs(direction_votes["BUY"] - direction_votes["SELL"])
        if direction_votes["BUY"] > direction_votes["SELL"] and vote_diff >= 2:
            direction = "BUY"
            # Verify trend alignment for BUY
            if is_downtrend and current_adx >= self.ADX_MODERATE:
                confluence = max(0, confluence - 20)
                reasons.append("Counter-trend BUY - reduced confidence")
        elif direction_votes["SELL"] > direction_votes["BUY"] and vote_diff >= 2:
            direction = "SELL"
            # Verify trend alignment for SELL
            if is_uptrend and current_adx >= self.ADX_MODERATE:
                confluence = max(0, confluence - 20)
                reasons.append("Counter-trend SELL - reduced confidence")
        else:
            direction = "HOLD"
            reasons.append("Insufficient vote difference for clear direction")
        
        # Volatility penalty for extreme conditions
        if vol_percentile > 85:
            confluence = max(0, confluence - 20)
            reasons.append("High volatility - reduced confidence")
        elif vol_percentile > 75:
            confluence = max(0, confluence - 10)
            reasons.append("Elevated volatility")
        
        # Calculate confidence - more conservative formula
        # Base confidence from confluence, with proper scaling
        base_confidence = confluence / 100
        # Add bonus for strong trend alignment
        if (direction == "BUY" and is_uptrend) or (direction == "SELL" and is_downtrend):
            base_confidence = min(1.0, base_confidence + 0.10)
        confidence = min(0.95, max(0.0, base_confidence))
        
        # Check thresholds (use instance variables for configurability)
        if confluence < self.min_confluence or confidence < self.min_confidence:
            return None
        
        if direction == "HOLD":
            return None
        
        # DYNAMIC ADX CHECK: Require minimum trend strength for signal
        if current_adx < adx_strong:
            logger.debug(f"Signal blocked: ADX {current_adx:.1f} < {adx_strong:.1f} threshold")
            return None
        
        # Build indicator snapshot with dynamic threshold info
        indicators = {
            "rsi": current_rsi,
            "ema_fast": current_ema_fast,
            "ema_slow": current_ema_slow,
            "macd": current_macd,
            "macd_signal": current_signal,
            "macd_histogram": current_histogram,
            "stoch_k": current_stoch_k,
            "stoch_d": current_stoch_d,
            "adx": current_adx,
            "plus_di": current_plus_di,
            "minus_di": current_minus_di,
            "atr": current_atr,
            "zscore": current_zscore,
            "regime": regime,
            "volatility_percentile": vol_percentile,
            "dynamic_thresholds": self.current_thresholds if self.use_dynamic_thresholds else None
        }
        
        signal = Signal(
            direction=direction,
            confidence=confidence,
            confluence=confluence,
            reason=" | ".join(reasons),
            indicators=indicators,
            timestamp=time.time(),
            symbol=self.symbol
        )
        
        self.last_signal = signal
        self.last_signal_time = signal.timestamp
        
        logger.info(
            f"[{self.symbol}] Signal: {direction} | "
            f"Confidence: {confidence:.2f} | "
            f"Confluence: {confluence} | "
            f"Reason: {signal.reason}"
        )
        
        return signal
    
    def get_current_analysis(self) -> Dict[str, Any]:
        """Get current indicator values without generating signal"""
        if len(self.closes) < 50:
            return {"status": "insufficient_data", "ticks": len(self.closes)}
        
        prices = list(self.closes)
        highs = list(self.highs)
        lows = list(self.lows)
        
        rsi = calculate_rsi(prices, self.RSI_PERIOD)
        ema_fast = calculate_ema(prices, self.EMA_FAST)
        ema_slow = calculate_ema(prices, self.EMA_SLOW)
        macd_line, signal_line, histogram = calculate_macd(prices)
        stoch_k, stoch_d = calculate_stochastic(highs, lows, prices)
        adx, plus_di, minus_di = calculate_adx(highs, lows, prices)
        atr = calculate_atr(highs, lows, prices)
        
        return {
            "status": "ready",
            "ticks": len(self.closes),
            "current_price": prices[-1] if prices else 0,
            "rsi": rsi[-1] if rsi else None,
            "ema_fast": ema_fast[-1] if ema_fast else None,
            "ema_slow": ema_slow[-1] if ema_slow else None,
            "macd": macd_line[-1] if macd_line else None,
            "macd_signal": signal_line[-1] if signal_line else None,
            "stoch_k": stoch_k[-1] if stoch_k else None,
            "adx": adx[-1] if adx else None,
            "plus_di": plus_di[-1] if plus_di else None,
            "minus_di": minus_di[-1] if minus_di else None,
            "atr": atr[-1] if atr else None,
            "regime": detect_regime(adx, atr, prices) if adx else "UNKNOWN"
        }
    
    def reset(self):
        """Reset strategy state"""
        self.tick_history.clear()
        self.highs.clear()
        self.lows.clear()
        self.closes.clear()
        self.last_signal_time = 0
        self.last_signal = None
        logger.info(f"[{self.symbol}] Strategy reset")
