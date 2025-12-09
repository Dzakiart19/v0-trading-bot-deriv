"""
AMT Accumulator Strategy - Growth rate management with TP/SL
Based on https://binarybot.live/amt/
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from collections import deque
from enum import Enum
import time
import math

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
            "analysis": self.analysis,
            "timestamp": self.timestamp
        }


class AccumulatorStrategy:
    """
    AMT Accumulator Strategy
    
    Features:
    - Growth rate management (1-5%)
    - Take Profit / Stop Loss tracking
    - Trend strength analysis
    - Volatility-based rate selection
    - Multi-symbol support
    """
    
    # Analysis windows
    SHORT_WINDOW = 10
    MEDIUM_WINDOW = 25
    LONG_WINDOW = 50
    VOLATILITY_WINDOW = 20
    
    # Thresholds
    MIN_CONFIDENCE = 0.65
    MIN_TICKS = 50
    
    # Growth rate selection criteria
    GROWTH_CRITERIA = {
        5: {"trend": "STRONG", "volatility": "LOW"},
        4: {"trend": "STRONG", "volatility": "MEDIUM"},
        3: {"trend": "MODERATE", "volatility": "LOW"},
        2: {"trend": "MODERATE", "volatility": "MEDIUM"},
        1: {"trend": "WEAK", "volatility": "HIGH"}
    }
    
    # Supported symbols
    SUPPORTED_SYMBOLS = [
        "R_100", "R_10", "R_25", "R_50", "R_75",
        "1HZ100V", "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V"
    ]
    
    def __init__(self):
        # Per-symbol tracking
        self.symbol_data: Dict[str, Dict] = {}
        
        # Initialize symbols
        for symbol in self.SUPPORTED_SYMBOLS:
            self._init_symbol(symbol)
        
        # Active accumulator positions
        self.positions: Dict[str, Dict] = {}
        
        # Default settings
        self.default_tp_multiplier = 2.0  # 2x stake
        self.default_sl_multiplier = 0.5  # 50% stake
        
        # Signal history
        self.signals: deque = deque(maxlen=100)
        self.last_signal_time = 0
        self.signal_cooldown = 10  # seconds
    
    def _init_symbol(self, symbol: str):
        """Initialize tracking for a symbol"""
        self.symbol_data[symbol] = {
            "prices": deque(maxlen=200),
            "last_tick": None
        }
    
    def add_tick(self, symbol: str, tick: Dict[str, Any]):
        """Add tick data for a symbol"""
        if symbol not in self.symbol_data:
            self._init_symbol(symbol)
        
        price = tick.get("quote", tick.get("price", 0))
        if price <= 0:
            return
        
        data = self.symbol_data[symbol]
        data["prices"].append(price)
        data["last_tick"] = tick
        
        # Update active position if exists
        if symbol in self.positions:
            self._update_position(symbol, price)
    
    def analyze(self, symbol: str) -> Optional[AccumulatorSignal]:
        """
        Analyze market conditions for accumulator entry
        
        Args:
            symbol: Trading symbol
            
        Returns:
            AccumulatorSignal with recommended action
        """
        if symbol not in self.symbol_data:
            return None
        
        data = self.symbol_data[symbol]
        prices = list(data["prices"])
        
        if len(prices) < self.MIN_TICKS:
            return None
        
        # Check cooldown
        if time.time() - self.last_signal_time < self.signal_cooldown:
            return None
        
        # Analyze trend
        trend_strength = self._analyze_trend(prices)
        
        # Analyze volatility
        volatility = self._analyze_volatility(prices)
        
        # Determine optimal growth rate
        growth_rate = self._select_growth_rate(trend_strength, volatility)
        
        # Calculate confidence
        confidence = self._calculate_confidence(trend_strength, volatility)
        
        if confidence < self.MIN_CONFIDENCE:
            return None
        
        # Calculate TP/SL
        current_price = prices[-1]
        atr = self._calculate_atr(prices)
        
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
            analysis={
                "short_trend": self._calculate_momentum(prices, self.SHORT_WINDOW),
                "medium_trend": self._calculate_momentum(prices, self.MEDIUM_WINDOW),
                "long_trend": self._calculate_momentum(prices, self.LONG_WINDOW),
                "atr": atr,
                "recommended_rate": f"{growth_rate}%"
            }
        )
        
        self.signals.append(signal)
        self.last_signal_time = time.time()
        
        logger.info(f"Accumulator Signal: {symbol} rate={growth_rate}% trend={trend_strength} vol={volatility}")
        
        return signal
    
    def _analyze_trend(self, prices: List[float]) -> str:
        """Analyze trend strength"""
        if len(prices) < self.LONG_WINDOW:
            return "WEAK"
        
        short_mom = self._calculate_momentum(prices, self.SHORT_WINDOW)
        medium_mom = self._calculate_momentum(prices, self.MEDIUM_WINDOW)
        long_mom = self._calculate_momentum(prices, self.LONG_WINDOW)
        
        # All aligned and strong
        if all(m > 0 for m in [short_mom, medium_mom, long_mom]) or all(m < 0 for m in [short_mom, medium_mom, long_mom]):
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
        
        if cv < 0.5:
            return "LOW"
        elif cv < 1.5:
            return "MEDIUM"
        else:
            return "HIGH"
    
    def _select_growth_rate(self, trend: str, volatility: str) -> int:
        """Select optimal growth rate based on conditions"""
        # Strong trend + Low volatility = aggressive
        if trend == "STRONG" and volatility == "LOW":
            return 5
        elif trend == "STRONG" and volatility == "MEDIUM":
            return 4
        elif trend == "STRONG" and volatility == "HIGH":
            return 3
        elif trend == "MODERATE" and volatility == "LOW":
            return 3
        elif trend == "MODERATE" and volatility == "MEDIUM":
            return 2
        else:
            return 1
    
    def _calculate_confidence(self, trend: str, volatility: str) -> float:
        """Calculate signal confidence"""
        base = 0.50
        
        # Trend bonus
        if trend == "STRONG":
            base += 0.20
        elif trend == "MODERATE":
            base += 0.10
        
        # Low volatility bonus
        if volatility == "LOW":
            base += 0.15
        elif volatility == "MEDIUM":
            base += 0.05
        else:
            base -= 0.05
        
        return min(base, 0.90)
    
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
            "volatility": self._analyze_volatility(prices) if len(prices) >= self.VOLATILITY_WINDOW else "N/A"
        }
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all symbols"""
        return {symbol: self.get_stats(symbol) for symbol in self.SUPPORTED_SYMBOLS}
