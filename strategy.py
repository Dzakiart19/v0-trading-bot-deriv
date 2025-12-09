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
    """
    
    # Configuration
    RSI_PERIOD = 14
    RSI_OVERSOLD_LOW = 22
    RSI_OVERSOLD_HIGH = 30
    RSI_OVERBOUGHT_LOW = 70
    RSI_OVERBOUGHT_HIGH = 78
    
    EMA_FAST = 9
    EMA_SLOW = 21
    
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    
    STOCH_PERIOD = 14
    STOCH_OVERSOLD = 20
    STOCH_OVERBOUGHT = 80
    
    ADX_PERIOD = 14
    ADX_STRONG = 22
    ADX_MODERATE = 18
    ADX_WEAK = 12
    
    ATR_PERIOD = 14
    
    MIN_CONFLUENCE = 40
    MIN_CONFIDENCE = 0.55
    SIGNAL_COOLDOWN = 12  # seconds
    
    def __init__(self, symbol: str = "R_100"):
        self.symbol = symbol
        self.tick_history: deque = deque(maxlen=200)
        self.last_signal_time = 0
        self.last_signal: Optional[Signal] = None
        
        # Configurable thresholds (can be modified for strategies like Sniper)
        self.min_confidence = self.MIN_CONFIDENCE
        self.min_confluence = self.MIN_CONFLUENCE
        
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
        
        # Confluence scoring
        confluence = 0
        direction_votes = {"BUY": 0, "SELL": 0}
        reasons = []
        
        # RSI Analysis (25 points max)
        if self.RSI_OVERSOLD_LOW <= current_rsi <= self.RSI_OVERSOLD_HIGH:
            confluence += 25
            direction_votes["BUY"] += 2
            reasons.append(f"RSI oversold ({current_rsi:.1f})")
        elif self.RSI_OVERBOUGHT_LOW <= current_rsi <= self.RSI_OVERBOUGHT_HIGH:
            confluence += 25
            direction_votes["SELL"] += 2
            reasons.append(f"RSI overbought ({current_rsi:.1f})")
        elif current_rsi < 40:
            confluence += 10
            direction_votes["BUY"] += 1
        elif current_rsi > 60:
            confluence += 10
            direction_votes["SELL"] += 1
        
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
        
        # Stochastic Analysis (15 points max)
        if current_stoch_k < self.STOCH_OVERSOLD:
            confluence += 15
            direction_votes["BUY"] += 1
            reasons.append(f"Stoch oversold ({current_stoch_k:.1f})")
        elif current_stoch_k > self.STOCH_OVERBOUGHT:
            confluence += 15
            direction_votes["SELL"] += 1
            reasons.append(f"Stoch overbought ({current_stoch_k:.1f})")
        
        # ADX/DMI Analysis (15 points max)
        if current_adx >= self.ADX_STRONG:
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
        
        # Mean Reversion (Z-Score) (10 points max)
        if current_zscore < -2:
            confluence += 10
            direction_votes["BUY"] += 1
            reasons.append(f"Mean reversion BUY (Z: {current_zscore:.2f})")
        elif current_zscore > 2:
            confluence += 10
            direction_votes["SELL"] += 1
            reasons.append(f"Mean reversion SELL (Z: {current_zscore:.2f})")
        
        # Determine direction
        if direction_votes["BUY"] > direction_votes["SELL"]:
            direction = "BUY"
        elif direction_votes["SELL"] > direction_votes["BUY"]:
            direction = "SELL"
        else:
            direction = "HOLD"
        
        # Volatility penalty for extreme conditions
        if vol_percentile > 90:
            confluence = max(0, confluence - 15)
            reasons.append("High volatility warning")
        
        # Calculate confidence
        confidence = min(1.0, confluence / 100 + 0.1)
        
        # Check thresholds (use instance variables for configurability)
        if confluence < self.min_confluence or confidence < self.min_confidence:
            return None
        
        if direction == "HOLD":
            return None
        
        # Build indicator snapshot
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
            "volatility_percentile": vol_percentile
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
