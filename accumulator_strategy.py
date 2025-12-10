"""
AMT Accumulator Strategy - Growth rate management with TP/SL
Enhanced with volatility filter, barrier distance prediction, and smart entry timing
Based on https://binarybot.live/amt/
"""

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GrowthRate(Enum):
    RATE_1 = 1
    RATE_2 = 2
    RATE_3 = 3
    RATE_4 = 4
    RATE_5 = 5


@dataclass
class AccumulatorSignal:
    action: str  # "ENTER", "EXIT", "HOLD"
    growth_rate: int  # 1-5%
    confidence: float
    trend_strength: str  # "STRONG", "MODERATE", "WEAK"
    volatility: str  # "LOW", "MEDIUM", "HIGH"
    entry_price: float
    take_profit: float
    stop_loss: float
    barrier_distance: float = 0.0  # Predicted barrier distance
    barrier_hit_probability: float = 0.0  # Probability of hitting barrier
    analysis: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "growth_rate": self.growth_rate,
            "confidence": self.confidence,
            "trend_strength": self.trend_strength,
            "volatility": self.volatility,
            "entry_price": self.entry_price,
            "take_profit": self.take_profit,
            "stop_loss": self.stop_loss,
            "barrier_distance": self.barrier_distance,
            "barrier_hit_probability": self.barrier_hit_probability,
            "analysis": self.analysis,
            "timestamp": self.timestamp
        }


class AccumulatorStrategy:
    """
    AMT Accumulator Strategy - Enhanced Version
    
    Features:
    - Conservative growth rate (default 1% for safety)
    - Volatility filter - avoid high volatility entries
    - Barrier distance prediction using ATR
    - Smart entry timing - wait for price to move away from barrier
    - Dynamic stake sizing based on balance
    - Cooldown period after losses
    - Trade history analysis for pattern detection
    """
    
    # Analysis windows
    SHORT_WINDOW = 10
    MEDIUM_WINDOW = 25
    LONG_WINDOW = 50
    VOLATILITY_WINDOW = 20
    
    # Thresholds - LOWERED for more signals
    MIN_CONFIDENCE = 0.55  # Lowered from 0.75 for more entries
    MIN_TICKS = 20  # Reduced from 30
    
    # Volatility Thresholds
    MAX_ATR_PERCENTILE = 70  # Don't trade if ATR > 70th percentile
    MAX_VOLATILITY_CV = 1.0  # Coefficient of variation threshold
    
    # Barrier Distance Settings
    MIN_BARRIER_DISTANCE_MULTIPLIER = 2.0  # Min distance = 2x ATR
    BARRIER_HIT_PROBABILITY_THRESHOLD = 0.30  # Max 30% probability of barrier hit
    
    # Growth rate selection - Conservative (always prefer 1%)
    GROWTH_CRITERIA = {
        5: {"trend": "STRONG", "volatility": "VERY_LOW"},  # Rarely used
        4: {"trend": "STRONG", "volatility": "VERY_LOW"},  # Rarely used
        3: {"trend": "STRONG", "volatility": "LOW"},       # Rarely used
        2: {"trend": "STRONG", "volatility": "LOW"},       # Sometimes
        1: {"trend": "MODERATE", "volatility": "MEDIUM"}   # Default - safest
    }
    
    # Supported symbols
    SUPPORTED_SYMBOLS = [
        "R_100", "R_10", "R_25", "R_50", "R_75",
        "1HZ100V", "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V"
    ]
    
    # Cooldown Settings - REDUCED for faster trading
    DEFAULT_COOLDOWN = 15  # Reduced from 30 seconds
    LOSS_COOLDOWN = 30  # Reduced from 60 seconds
    CONSECUTIVE_LOSS_COOLDOWN = 60  # Reduced from 120 seconds
    
    def __init__(self):
        # Per-symbol tracking
        self.symbol_data: Dict[str, Dict] = {}
        
        # Initialize symbols
        for symbol in self.SUPPORTED_SYMBOLS:
            self._init_symbol(symbol)
        
        # Active accumulator positions
        self.positions: Dict[str, Dict] = {}
        
        # Conservative TP/SL settings
        self.default_tp_multiplier = 1.2  # 1.2x stake TP (reduced from 1.5)
        self.default_sl_multiplier = 0.3  # 30% stake SL (reduced from 50%)
        
        # Signal history
        self.signals: deque = deque(maxlen=100)
        self.last_signal_time = 0
        self.signal_cooldown = 30  # Increased from 10 seconds
        
        # Trade history for pattern analysis
        self.trade_history: deque = deque(maxlen=50)
        self.consecutive_losses = 0
        self.last_trade_result: Optional[str] = None
        self.last_loss_time = 0
        
        # ATR history for volatility percentile
        self.atr_history: deque = deque(maxlen=100)
        
        # Dynamic stake settings
        self.min_stake_percent = 0.005  # 0.5% of balance minimum
        self.max_stake_percent = 0.02   # 2% of balance maximum
    
    def _init_symbol(self, symbol: str):
        """Initialize tracking for a symbol"""
        self.symbol_data[symbol] = {
            "prices": deque(maxlen=200),
            "last_tick": None,
            "atr_values": deque(maxlen=50),
            "volatility_history": deque(maxlen=50)
        }
    
    def record_trade_result(self, is_win: bool, profit: float = 0.0):
        """Record trade result for pattern analysis"""
        result = "WIN" if is_win else "LOSS"
        self.trade_history.append({
            "result": result,
            "profit": profit,
            "timestamp": time.time()
        })
        
        if is_win:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.last_loss_time = time.time()
        
        self.last_trade_result = result
        logger.info(f"Accumulator trade recorded: {result}, consecutive_losses={self.consecutive_losses}")
    
    def _get_current_cooldown(self) -> float:
        """Get current cooldown based on recent performance"""
        if self.consecutive_losses >= 3:
            return self.CONSECUTIVE_LOSS_COOLDOWN
        elif self.consecutive_losses >= 1:
            return self.LOSS_COOLDOWN
        return self.signal_cooldown
    
    def _is_in_cooldown(self) -> bool:
        """Check if we're in cooldown period"""
        current_time = time.time()
        cooldown = self._get_current_cooldown()
        
        # Check cooldown from last signal
        if current_time - self.last_signal_time < cooldown:
            return True
        
        # Extra cooldown after losses
        if self.consecutive_losses > 0:
            time_since_loss = current_time - self.last_loss_time
            if time_since_loss < self.LOSS_COOLDOWN:
                return True
        
        return False
    
    def calculate_dynamic_stake(self, balance: float) -> float:
        """Calculate stake based on balance - no hardcoded minimum"""
        if balance <= 0:
            return 0.35  # Absolute minimum
        
        # Base stake: 1% of balance
        base_stake = balance * 0.01
        
        # Adjust based on consecutive losses
        if self.consecutive_losses >= 2:
            base_stake *= 0.5  # Reduce stake after losses
        
        # Apply min/max limits based on balance
        min_stake = max(0.35, balance * self.min_stake_percent)
        max_stake = balance * self.max_stake_percent
        
        stake = max(min_stake, min(base_stake, max_stake))
        
        logger.debug(f"Dynamic stake calculated: ${stake:.2f} (balance: ${balance:.2f})")
        return stake
    
    def add_tick(self, symbol: str, tick: Dict[str, Any]) -> Optional[AccumulatorSignal]:
        """Add tick data for a symbol and analyze for signals"""
        if symbol not in self.symbol_data:
            self._init_symbol(symbol)
        
        price = tick.get("quote", tick.get("price", 0))
        if price <= 0:
            return None
        
        data = self.symbol_data[symbol]
        data["prices"].append(price)
        data["last_tick"] = tick
        
        # Update ATR tracking
        prices = list(data["prices"])
        if len(prices) >= 15:
            current_atr = self._calculate_atr(prices)
            data["atr_values"].append(current_atr)
            self.atr_history.append(current_atr)
        
        # Update active position if exists
        if symbol in self.positions:
            self._update_position(symbol, price)
            return None  # Don't signal when position is open
        
        # Analyze for new entry signal
        return self.analyze(symbol)
    
    def analyze(self, symbol: str) -> Optional[AccumulatorSignal]:
        """
        Analyze market conditions for accumulator entry
        Enhanced with volatility filter and barrier distance prediction
        """
        if symbol not in self.symbol_data:
            return None
        
        data = self.symbol_data[symbol]
        prices = list(data["prices"])
        
        if len(prices) < self.MIN_TICKS:
            return None
        
        # Check cooldown (including loss cooldown)
        if self._is_in_cooldown():
            logger.debug(f"Accumulator in cooldown, consecutive_losses={self.consecutive_losses}")
            return None
        
        # Calculate volatility metrics
        atr = self._calculate_atr(prices)
        volatility = self._analyze_volatility(prices)
        volatility_cv = self._calculate_volatility_cv(prices)
        
        # VOLATILITY FILTER - Skip high volatility conditions
        if volatility == "HIGH":
            logger.debug("Skipping - volatility too high for accumulator")
            return None
        
        if volatility_cv > self.MAX_VOLATILITY_CV:
            logger.debug(f"Skipping - volatility CV ({volatility_cv:.2f}) > threshold ({self.MAX_VOLATILITY_CV})")
            return None
        
        # Check ATR percentile
        atr_percentile = self._get_atr_percentile(atr)
        if atr_percentile > self.MAX_ATR_PERCENTILE:
            logger.debug(f"Skipping - ATR percentile ({atr_percentile:.0f}) > threshold ({self.MAX_ATR_PERCENTILE})")
            return None
        
        # Analyze trend
        trend_strength = self._analyze_trend(prices)
        
        # CONSERVATIVE: Only trade with MODERATE or STRONG trend
        if trend_strength == "WEAK":
            logger.debug("Skipping - trend too weak for accumulator")
            return None
        
        # Calculate barrier distance
        current_price = prices[-1]
        barrier_distance = self._calculate_barrier_distance(prices, atr)
        
        # Check if price is too close to potential barrier
        min_safe_distance = atr * self.MIN_BARRIER_DISTANCE_MULTIPLIER
        if barrier_distance < min_safe_distance:
            logger.debug(f"Skipping - price too close to barrier ({barrier_distance:.4f} < {min_safe_distance:.4f})")
            return None
        
        # Calculate probability of hitting barrier
        barrier_hit_prob = self._calculate_barrier_hit_probability(prices, atr)
        if barrier_hit_prob > self.BARRIER_HIT_PROBABILITY_THRESHOLD:
            logger.debug(f"Skipping - barrier hit probability too high ({barrier_hit_prob:.1%})")
            return None
        
        # Smart entry timing - check if price is moving away from barrier
        if not self._is_good_entry_timing(prices):
            logger.debug("Skipping - waiting for better entry timing")
            return None
        
        # Determine optimal growth rate - ALWAYS prefer 1% for safety
        growth_rate = self._select_growth_rate(trend_strength, volatility)
        
        # Calculate confidence with stricter requirements
        confidence = self._calculate_confidence(trend_strength, volatility, barrier_hit_prob, atr_percentile)
        
        if confidence < self.MIN_CONFIDENCE:
            logger.debug(f"Skipping - confidence too low ({confidence:.2%} < {self.MIN_CONFIDENCE:.2%})")
            return None
        
        # Calculate TP/SL
        take_profit = current_price * (1 + (growth_rate * self.default_tp_multiplier / 100))
        stop_loss = current_price * (1 - (self.default_sl_multiplier / 100))
        
        signal = AccumulatorSignal(
            action="ENTER",
            growth_rate=growth_rate,
            confidence=confidence,
            trend_strength=trend_strength,
            volatility=volatility,
            entry_price=current_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            barrier_distance=barrier_distance,
            barrier_hit_probability=barrier_hit_prob,
            analysis={
                "short_trend": self._calculate_momentum(prices, self.SHORT_WINDOW),
                "medium_trend": self._calculate_momentum(prices, self.MEDIUM_WINDOW),
                "long_trend": self._calculate_momentum(prices, self.LONG_WINDOW),
                "atr": atr,
                "atr_percentile": atr_percentile,
                "volatility_cv": volatility_cv,
                "consecutive_losses": self.consecutive_losses,
                "recommended_rate": f"{growth_rate}%"
            }
        )
        
        self.signals.append(signal)
        self.last_signal_time = time.time()
        
        logger.info(
            f"Accumulator Signal: {symbol} rate={growth_rate}% trend={trend_strength} "
            f"vol={volatility} conf={confidence:.1%} barrier_prob={barrier_hit_prob:.1%}"
        )
        
        return signal
    
    def _analyze_trend(self, prices: List[float]) -> str:
        """Analyze trend strength"""
        if len(prices) < self.LONG_WINDOW:
            return "WEAK"
        
        short_mom = self._calculate_momentum(prices, self.SHORT_WINDOW)
        medium_mom = self._calculate_momentum(prices, self.MEDIUM_WINDOW)
        long_mom = self._calculate_momentum(prices, self.LONG_WINDOW)
        
        # All aligned and strong
        if all(m > 0 for m in [short_mom, medium_mom, long_mom]) or \
           all(m < 0 for m in [short_mom, medium_mom, long_mom]):
            avg_strength = abs(short_mom + medium_mom + long_mom) / 3
            if avg_strength > 0.1:
                return "STRONG"
            elif avg_strength > 0.05:
                return "MODERATE"
        
        return "WEAK"
    
    def _analyze_volatility(self, prices: List[float]) -> str:
        """Analyze current volatility"""
        if len(prices) < self.VOLATILITY_WINDOW:
            return "MEDIUM"
        
        recent = prices[-self.VOLATILITY_WINDOW:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std_dev = math.sqrt(variance)
        
        cv = (std_dev / mean) * 100  # Coefficient of variation
        
        if cv < 0.3:
            return "VERY_LOW"
        elif cv < 0.5:
            return "LOW"
        elif cv < 1.0:
            return "MEDIUM"
        else:
            return "HIGH"
    
    def _calculate_volatility_cv(self, prices: List[float]) -> float:
        """Calculate coefficient of variation for volatility"""
        if len(prices) < self.VOLATILITY_WINDOW:
            return 1.0
        
        recent = prices[-self.VOLATILITY_WINDOW:]
        mean = sum(recent) / len(recent)
        if mean == 0:
            return 1.0
        
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        std_dev = math.sqrt(variance)
        
        return (std_dev / mean) * 100
    
    def _get_atr_percentile(self, current_atr: float) -> float:
        """Get current ATR percentile compared to history"""
        if len(self.atr_history) < 10:
            return 50.0
        
        atr_list = sorted(list(self.atr_history))
        position = sum(1 for atr in atr_list if atr <= current_atr)
        
        return (position / len(atr_list)) * 100
    
    def _calculate_barrier_distance(self, prices: List[float], atr: float) -> float:
        """Calculate estimated distance to barrier based on recent price action"""
        if len(prices) < 20:
            return atr * 2
        
        recent = prices[-20:]
        high = max(recent)
        low = min(recent)
        current = prices[-1]
        
        # Distance to nearest extreme (proxy for barrier)
        dist_to_high = high - current
        dist_to_low = current - low
        
        return min(dist_to_high, dist_to_low)
    
    def _calculate_barrier_hit_probability(self, prices: List[float], atr: float) -> float:
        """
        Estimate probability of hitting barrier within N ticks
        Based on historical volatility and recent price movements
        """
        if len(prices) < 30:
            return 0.5  # Uncertain
        
        # Calculate recent tick-to-tick changes
        changes = []
        for i in range(1, min(30, len(prices))):
            change = abs(prices[-i] - prices[-i-1])
            changes.append(change)
        
        if not changes:
            return 0.5
        
        avg_change = sum(changes) / len(changes)
        max_change = max(changes)
        
        # Barrier distance (approximated)
        barrier_dist = atr * 1.5  # Accumulator barrier is typically 1-2x ATR
        
        # Simple probability based on how often max_change exceeds barrier distance
        large_moves = sum(1 for c in changes if c > barrier_dist * 0.5)
        prob = large_moves / len(changes)
        
        return min(prob, 1.0)
    
    def _is_good_entry_timing(self, prices: List[float]) -> bool:
        """
        Check if current timing is good for entry
        Price should be moving away from potential barrier (recent high/low)
        """
        if len(prices) < 20:
            return True
        
        recent = prices[-20:]
        current = prices[-1]
        prev = prices[-5]  # 5 ticks ago
        
        high = max(recent)
        low = min(recent)
        mid = (high + low) / 2
        
        # Check if price is in the middle zone (safer)
        range_size = high - low
        if range_size == 0:
            return True
        
        position = (current - low) / range_size
        
        # Best entry when price is between 30-70% of range
        if 0.3 <= position <= 0.7:
            return True
        
        # If near extreme, check if moving away
        if position < 0.3:  # Near low
            return current > prev  # Should be moving up
        else:  # Near high
            return current < prev  # Should be moving down
    
    def _select_growth_rate(self, trend: str, volatility: str) -> int:
        """
        Select optimal growth rate - CONSERVATIVE APPROACH
        Lower growth = wider barriers = less barrier hits
        Always default to 1% unless conditions are perfect
        """
        # Only use higher rates in very stable conditions
        if trend == "STRONG" and volatility == "VERY_LOW":
            return 2  # Max 2% even in best conditions
        elif trend == "STRONG" and volatility == "LOW":
            return 1  # Stay safe
        else:
            return 1  # Default to safest rate
    
    def _calculate_confidence(
        self, 
        trend: str, 
        volatility: str, 
        barrier_prob: float,
        atr_percentile: float
    ) -> float:
        """Calculate signal confidence with additional factors"""
        base = 0.50
        
        # Trend bonus
        if trend == "STRONG":
            base += 0.20
        elif trend == "MODERATE":
            base += 0.10
        
        # Volatility bonus
        if volatility == "VERY_LOW":
            base += 0.15
        elif volatility == "LOW":
            base += 0.10
        elif volatility == "MEDIUM":
            base += 0.05
        else:
            base -= 0.10  # Penalty for high volatility
        
        # Barrier probability penalty
        if barrier_prob < 0.1:
            base += 0.10
        elif barrier_prob < 0.2:
            base += 0.05
        elif barrier_prob > 0.3:
            base -= 0.10
        
        # ATR percentile bonus (lower is better)
        if atr_percentile < 30:
            base += 0.05
        elif atr_percentile > 70:
            base -= 0.10
        
        # Consecutive loss penalty
        if self.consecutive_losses >= 2:
            base -= 0.10
        
        return max(0, min(base, 0.95))
    
    def _calculate_momentum(self, prices: List[float], window: int) -> float:
        """Calculate momentum for window"""
        if len(prices) < window + 1:
            return 0
        
        recent = prices[-window:]
        oldest = prices[-(window+1)]
        
        if oldest == 0:
            return 0
        
        return (recent[-1] - oldest) / oldest * 100
    
    def _calculate_atr(self, prices: List[float], period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(prices) < period + 1:
            return 0
        
        trs = []
        for i in range(-period, 0):
            high = max(prices[i], prices[i-1])
            low = min(prices[i], prices[i-1])
            trs.append(high - low)
        
        return sum(trs) / len(trs) if trs else 0
    
    def enter_position(self, symbol: str, stake: float, growth_rate: int):
        """Enter accumulator position"""
        if symbol not in self.symbol_data:
            return
        
        data = self.symbol_data[symbol]
        if not data["prices"]:
            return
        
        entry_price = list(data["prices"])[-1]
        
        self.positions[symbol] = {
            "entry_price": entry_price,
            "current_price": entry_price,
            "stake": stake,
            "growth_rate": growth_rate,
            "take_profit": entry_price * (1 + (growth_rate * self.default_tp_multiplier / 100)),
            "stop_loss": entry_price * (1 - (self.default_sl_multiplier / 100)),
            "entry_time": time.time(),
            "current_value": stake,
            "pnl": 0
        }
        
        logger.info(f"Entered Accumulator: {symbol} @ {entry_price} rate={growth_rate}%")
    
    def _update_position(self, symbol: str, current_price: float):
        """Update position with current price"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        pos["current_price"] = current_price
        
        # Calculate P&L
        price_change = (current_price - pos["entry_price"]) / pos["entry_price"]
        pos["current_value"] = pos["stake"] * (1 + price_change * pos["growth_rate"])
        pos["pnl"] = pos["current_value"] - pos["stake"]
        
        # Check TP/SL
        if current_price >= pos["take_profit"]:
            logger.info(f"Accumulator TP hit: {symbol} PnL: {pos['pnl']:.2f}")
        elif current_price <= pos["stop_loss"]:
            logger.info(f"Accumulator SL hit: {symbol} PnL: {pos['pnl']:.2f}")
    
    def exit_position(self, symbol: str) -> Optional[Dict]:
        """Exit accumulator position"""
        if symbol not in self.positions:
            return None
        
        pos = self.positions.pop(symbol)
        logger.info(f"Exited Accumulator: {symbol} PnL: {pos['pnl']:.2f}")
        return pos
    
    def get_position(self, symbol: str) -> Optional[Dict]:
        """Get current position for symbol"""
        return self.positions.get(symbol)
    
    def get_all_positions(self) -> Dict[str, Dict]:
        """Get all active positions"""
        return self.positions.copy()
    
    def get_stats(self, symbol: str) -> Dict[str, Any]:
        """Get statistics for a symbol"""
        if symbol not in self.symbol_data:
            return {}
        
        data = self.symbol_data[symbol]
        prices = list(data["prices"])
        
        return {
            "symbol": symbol,
            "ticks_count": len(prices),
            "last_price": prices[-1] if prices else 0,
            "position": self.get_position(symbol),
            "trend": self._analyze_trend(prices) if len(prices) >= self.MIN_TICKS else "N/A",
            "volatility": self._analyze_volatility(prices) if len(prices) >= self.VOLATILITY_WINDOW else "N/A",
            "consecutive_losses": self.consecutive_losses,
            "cooldown_remaining": max(0, self._get_current_cooldown() - (time.time() - self.last_signal_time))
        }
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all symbols"""
        return {symbol: self.get_stats(symbol) for symbol in self.SUPPORTED_SYMBOLS}
    
    def get_trade_analysis(self) -> Dict[str, Any]:
        """Analyze recent trade performance"""
        if not self.trade_history:
            return {"total": 0, "win_rate": 0, "recommendation": "Not enough data"}
        
        trades = list(self.trade_history)
        wins = sum(1 for t in trades if t["result"] == "WIN")
        total = len(trades)
        win_rate = (wins / total) * 100 if total > 0 else 0
        
        # Recommendation based on performance
        if win_rate < 40 and total >= 5:
            recommendation = "Consider pausing - win rate too low"
        elif self.consecutive_losses >= 3:
            recommendation = "Consider pausing - losing streak detected"
        elif win_rate > 60:
            recommendation = "Strategy performing well"
        else:
            recommendation = "Continue with caution"
        
        return {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": win_rate,
            "consecutive_losses": self.consecutive_losses,
            "recommendation": recommendation
        }
