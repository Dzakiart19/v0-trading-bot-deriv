"""
Technical Indicators - RSI, EMA, MACD, Stochastic, ADX, ATR calculations
"""

import math
from typing import Dict, List, Optional, Tuple
from collections import deque

def safe_float(value, default=0.0) -> float:
    """Safely convert to float, handling NaN/Inf"""
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default

def calculate_ema(prices: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average"""
    if len(prices) < period:
        return []
    
    ema = []
    multiplier = 2 / (period + 1)
    
    # First EMA is SMA
    sma = sum(prices[:period]) / period
    ema.append(safe_float(sma))
    
    for price in prices[period:]:
        new_ema = (safe_float(price) - ema[-1]) * multiplier + ema[-1]
        ema.append(safe_float(new_ema))
    
    return ema

def calculate_sma(prices: List[float], period: int) -> List[float]:
    """Calculate Simple Moving Average"""
    if len(prices) < period:
        return []
    
    sma = []
    for i in range(period - 1, len(prices)):
        avg = sum(prices[i - period + 1:i + 1]) / period
        sma.append(safe_float(avg))
    
    return sma

def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """Calculate Relative Strength Index"""
    if len(prices) < period + 1:
        return []
    
    gains = []
    losses = []
    
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    
    rsi = []
    
    # First RSI using SMA
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        rsi.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi.append(safe_float(100 - (100 / (1 + rs))))
    
    # Subsequent RSI using EMA
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(safe_float(100 - (100 / (1 + rs))))
    
    return rsi

def calculate_macd(
    prices: List[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[List[float], List[float], List[float]]:
    """
    Calculate MACD
    Returns: (macd_line, signal_line, histogram)
    """
    if len(prices) < slow_period + signal_period:
        return [], [], []
    
    ema_fast = calculate_ema(prices, fast_period)
    ema_slow = calculate_ema(prices, slow_period)
    
    # Align EMAs
    offset = slow_period - fast_period
    ema_fast = ema_fast[offset:]
    
    if len(ema_fast) != len(ema_slow):
        min_len = min(len(ema_fast), len(ema_slow))
        ema_fast = ema_fast[-min_len:]
        ema_slow = ema_slow[-min_len:]
    
    macd_line = [safe_float(f - s) for f, s in zip(ema_fast, ema_slow)]
    
    if len(macd_line) < signal_period:
        return [], [], []
    
    signal_line = calculate_ema(macd_line, signal_period)
    
    # Align for histogram
    macd_trimmed = macd_line[-(len(signal_line)):]
    histogram = [safe_float(m - s) for m, s in zip(macd_trimmed, signal_line)]
    
    return macd_line, signal_line, histogram

def calculate_stochastic(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3
) -> Tuple[List[float], List[float]]:
    """
    Calculate Stochastic Oscillator
    Returns: (%K, %D)
    """
    if len(closes) < period:
        return [], []
    
    raw_k = []
    
    for i in range(period - 1, len(closes)):
        period_high = max(highs[i - period + 1:i + 1])
        period_low = min(lows[i - period + 1:i + 1])
        
        if period_high == period_low:
            raw_k.append(50.0)
        else:
            k = ((closes[i] - period_low) / (period_high - period_low)) * 100
            raw_k.append(safe_float(k))
    
    # Smooth %K
    k_line = calculate_sma(raw_k, smooth_k) if smooth_k > 1 else raw_k
    
    # Calculate %D (SMA of %K)
    d_line = calculate_sma(k_line, smooth_d) if smooth_d > 1 else k_line
    
    return k_line, d_line

def calculate_adx(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> Tuple[List[float], List[float], List[float]]:
    """
    Calculate Average Directional Index
    Returns: (ADX, +DI, -DI)
    """
    if len(closes) < period + 1:
        return [], [], []
    
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []
    
    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        prev_high = highs[i - 1]
        prev_low = lows[i - 1]
        
        # True Range
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_list.append(safe_float(tr))
        
        # Directional Movement
        plus_dm = max(0, high - prev_high) if (high - prev_high) > (prev_low - low) else 0
        minus_dm = max(0, prev_low - low) if (prev_low - low) > (high - prev_high) else 0
        
        plus_dm_list.append(safe_float(plus_dm))
        minus_dm_list.append(safe_float(minus_dm))
    
    # Smoothed values
    atr = calculate_ema(tr_list, period)
    smoothed_plus = calculate_ema(plus_dm_list, period)
    smoothed_minus = calculate_ema(minus_dm_list, period)
    
    if not atr or not smoothed_plus or not smoothed_minus:
        return [], [], []
    
    # Align lengths
    min_len = min(len(atr), len(smoothed_plus), len(smoothed_minus))
    atr = atr[-min_len:]
    smoothed_plus = smoothed_plus[-min_len:]
    smoothed_minus = smoothed_minus[-min_len:]
    
    plus_di = []
    minus_di = []
    dx_list = []
    
    for i in range(len(atr)):
        if atr[i] == 0:
            plus_di.append(0.0)
            minus_di.append(0.0)
            dx_list.append(0.0)
        else:
            pdi = (smoothed_plus[i] / atr[i]) * 100
            mdi = (smoothed_minus[i] / atr[i]) * 100
            plus_di.append(safe_float(pdi))
            minus_di.append(safe_float(mdi))
            
            di_sum = pdi + mdi
            if di_sum == 0:
                dx_list.append(0.0)
            else:
                dx = (abs(pdi - mdi) / di_sum) * 100
                dx_list.append(safe_float(dx))
    
    # ADX is smoothed DX
    adx = calculate_ema(dx_list, period)
    
    # Align output
    if adx:
        offset = len(plus_di) - len(adx)
        plus_di = plus_di[offset:]
        minus_di = minus_di[offset:]
    
    return adx, plus_di, minus_di

def calculate_atr(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14
) -> List[float]:
    """Calculate Average True Range"""
    if len(closes) < period + 1:
        return []
    
    tr_list = []
    
    for i in range(1, len(closes)):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        tr_list.append(safe_float(tr))
    
    return calculate_ema(tr_list, period)

def calculate_hma(prices: List[float], period: int = 9) -> List[float]:
    """Calculate Hull Moving Average"""
    if len(prices) < period:
        return []
    
    half_period = period // 2
    sqrt_period = int(math.sqrt(period))
    
    wma_half = calculate_wma(prices, half_period)
    wma_full = calculate_wma(prices, period)
    
    if not wma_half or not wma_full:
        return []
    
    # Align
    offset = len(wma_half) - len(wma_full)
    wma_half = wma_half[offset:]
    
    raw_hma = [2 * h - f for h, f in zip(wma_half, wma_full)]
    
    return calculate_wma(raw_hma, sqrt_period)

def calculate_wma(prices: List[float], period: int) -> List[float]:
    """Calculate Weighted Moving Average"""
    if len(prices) < period:
        return []
    
    wma = []
    weights = list(range(1, period + 1))
    weight_sum = sum(weights)
    
    for i in range(period - 1, len(prices)):
        weighted_sum = sum(
            prices[i - period + 1 + j] * weights[j]
            for j in range(period)
        )
        wma.append(safe_float(weighted_sum / weight_sum))
    
    return wma

def calculate_bollinger_bands(
    prices: List[float],
    period: int = 20,
    std_dev: float = 2.0
) -> Tuple[List[float], List[float], List[float]]:
    """
    Calculate Bollinger Bands
    Returns: (upper, middle, lower)
    """
    if len(prices) < period:
        return [], [], []
    
    middle = calculate_sma(prices, period)
    upper = []
    lower = []
    
    for i in range(len(middle)):
        idx = i + period - 1
        window = prices[idx - period + 1:idx + 1]
        
        mean = middle[i]
        variance = sum((p - mean) ** 2 for p in window) / period
        std = math.sqrt(variance)
        
        upper.append(safe_float(mean + std_dev * std))
        lower.append(safe_float(mean - std_dev * std))
    
    return upper, middle, lower

def calculate_zscore(prices: List[float], period: int = 20) -> List[float]:
    """Calculate Z-Score for mean reversion detection"""
    if len(prices) < period:
        return []
    
    zscores = []
    
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((p - mean) ** 2 for p in window) / period
        std = math.sqrt(variance) if variance > 0 else 0.0001
        
        zscore = (prices[i] - mean) / std
        zscores.append(safe_float(zscore))
    
    return zscores

def detect_regime(
    adx_values: List[float],
    atr_values: List[float],
    prices: List[float]
) -> str:
    """
    Detect market regime: TRENDING, RANGING, or TRANSITIONAL
    """
    if not adx_values or not atr_values:
        return "UNKNOWN"
    
    current_adx = adx_values[-1] if adx_values else 0
    
    # ADX thresholds
    if current_adx >= 25:
        return "TRENDING"
    elif current_adx <= 15:
        return "RANGING"
    else:
        return "TRANSITIONAL"

def calculate_volatility_percentile(
    atr_values: List[float],
    lookback: int = 100
) -> float:
    """Calculate current volatility as percentile of recent history"""
    if len(atr_values) < 2:
        return 50.0
    
    recent = atr_values[-lookback:] if len(atr_values) >= lookback else atr_values
    current = atr_values[-1]
    
    below_count = sum(1 for v in recent if v < current)
    percentile = (below_count / len(recent)) * 100
    
    return safe_float(percentile)


class IndicatorCache:
    """
    Incremental indicator cache for performance optimization.
    Caches EMA, RSI, MACD values and only updates incrementally when new data arrives.
    """
    
    def __init__(self, max_size: int = 200):
        self.max_size = max_size
        self._prices: deque = deque(maxlen=max_size)
        self._ema_cache: Dict[int, float] = {}  # period -> latest EMA
        self._rsi_cache: Optional[float] = None
        self._rsi_avg_gain: float = 0.0
        self._rsi_avg_loss: float = 0.0
        self._rsi_period: int = 14
        self._macd_cache: Optional[Dict[str, float]] = None
        self._adx_cache: Optional[float] = None
        self._last_update_count: int = 0
        self._warmup_complete: bool = False
    
    def add_price(self, price: float) -> None:
        """Add new price and update cached indicators incrementally"""
        prev_price = self._prices[-1] if self._prices else price
        self._prices.append(price)
        
        # Update EMA caches incrementally
        for period, last_ema in list(self._ema_cache.items()):
            if len(self._prices) >= period:
                multiplier = 2 / (period + 1)
                new_ema = (price - last_ema) * multiplier + last_ema
                self._ema_cache[period] = safe_float(new_ema)
        
        # Update RSI incrementally
        if len(self._prices) > self._rsi_period:
            change = price - prev_price
            gain = max(0, change)
            loss = max(0, -change)
            self._rsi_avg_gain = (self._rsi_avg_gain * (self._rsi_period - 1) + gain) / self._rsi_period
            self._rsi_avg_loss = (self._rsi_avg_loss * (self._rsi_period - 1) + loss) / self._rsi_period
            if self._rsi_avg_loss == 0:
                self._rsi_cache = 100.0
            else:
                rs = self._rsi_avg_gain / self._rsi_avg_loss
                self._rsi_cache = safe_float(100 - (100 / (1 + rs)))
        
        self._last_update_count += 1
        if self._last_update_count >= 50:
            self._warmup_complete = True
    
    def get_ema(self, period: int) -> Optional[float]:
        """Get cached EMA value, initializing if needed"""
        if len(self._prices) < period:
            return None
        
        if period not in self._ema_cache:
            # Initialize EMA with SMA
            prices_list = list(self._prices)
            sma = sum(prices_list[:period]) / period
            self._ema_cache[period] = safe_float(sma)
            # Calculate full EMA from start
            ema = sma
            multiplier = 2 / (period + 1)
            for p in prices_list[period:]:
                ema = (p - ema) * multiplier + ema
            self._ema_cache[period] = safe_float(ema)
        
        return self._ema_cache.get(period)
    
    def get_rsi(self, period: int = 14) -> Optional[float]:
        """Get cached RSI value"""
        if len(self._prices) < period + 1:
            return None
        
        if self._rsi_cache is None or self._rsi_period != period:
            # Initialize RSI
            self._rsi_period = period
            prices_list = list(self._prices)
            gains = []
            losses = []
            for i in range(1, len(prices_list)):
                change = prices_list[i] - prices_list[i-1]
                gains.append(max(0, change))
                losses.append(max(0, -change))
            
            if len(gains) >= period:
                self._rsi_avg_gain = sum(gains[:period]) / period
                self._rsi_avg_loss = sum(losses[:period]) / period
                
                for i in range(period, len(gains)):
                    self._rsi_avg_gain = (self._rsi_avg_gain * (period - 1) + gains[i]) / period
                    self._rsi_avg_loss = (self._rsi_avg_loss * (period - 1) + losses[i]) / period
                
                if self._rsi_avg_loss == 0:
                    self._rsi_cache = 100.0
                else:
                    rs = self._rsi_avg_gain / self._rsi_avg_loss
                    self._rsi_cache = safe_float(100 - (100 / (1 + rs)))
        
        return self._rsi_cache
    
    def get_macd(self) -> Optional[Dict[str, float]]:
        """Get cached MACD values (recalculated on demand)"""
        if len(self._prices) < 35:  # 26 + 9 signal period
            return None
        
        prices_list = list(self._prices)
        macd_line, signal_line, histogram = calculate_macd(prices_list)
        if macd_line and signal_line and histogram:
            self._macd_cache = {
                "macd": macd_line[-1],
                "signal": signal_line[-1],
                "histogram": histogram[-1]
            }
        return self._macd_cache
    
    def is_warmed_up(self) -> bool:
        """Check if cache has enough data for reliable signals"""
        return self._warmup_complete and len(self._prices) >= 50
    
    def get_price_count(self) -> int:
        """Get number of prices in cache"""
        return len(self._prices)
    
    def clear(self):
        """Clear all cached data"""
        self._prices.clear()
        self._ema_cache.clear()
        self._rsi_cache = None
        self._macd_cache = None
        self._last_update_count = 0
        self._warmup_complete = False



class TechnicalIndicators:
    """
    Class wrapper for technical indicator calculations
    Used by Terminal and Sniper strategies
    """
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculate RSI and return latest value"""
        result = calculate_rsi(prices, period)
        return result[-1] if result else None
    
    def calculate_ema(self, prices: List[float], period: int) -> Optional[float]:
        """Calculate EMA and return latest value"""
        result = calculate_ema(prices, period)
        return result[-1] if result else None
    
    def calculate_macd(self, prices: List[float]) -> Optional[dict]:
        """Calculate MACD and return latest values as dict"""
        macd_line, signal_line, histogram = calculate_macd(prices)
        if not macd_line or not signal_line or not histogram:
            return None
        return {
            "macd": macd_line[-1],
            "signal": signal_line[-1],
            "histogram": histogram[-1]
        }
    
    def calculate_stochastic(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculate Stochastic %K and return latest value"""
        k_line, d_line = calculate_stochastic(prices, prices, prices, period)
        return k_line[-1] if k_line else None
    
    def calculate_adx(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculate ADX and return latest value"""
        adx, plus_di, minus_di = calculate_adx(prices, prices, prices, period)
        return adx[-1] if adx else None
    
    def calculate_atr(self, prices: List[float], period: int = 14) -> Optional[float]:
        """Calculate ATR and return latest value"""
        result = calculate_atr(prices, prices, prices, period)
        return result[-1] if result else None
