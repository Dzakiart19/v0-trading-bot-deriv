"""
Symbol Configuration - Centralized symbol definitions for Deriv trading
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass

@dataclass
class SymbolConfig:
    """Configuration for a trading symbol"""
    symbol: str
    name: str
    category: str
    min_stake: float
    max_stake: float
    min_duration: int
    max_duration: int
    duration_unit: str  # 't' for ticks, 'm' for minutes, 'd' for days
    supports_ticks: bool
    supports_minutes: bool
    supports_days: bool
    pip_size: float
    
# Symbol definitions
SYMBOLS: Dict[str, SymbolConfig] = {
    # Synthetic Indices - Volatility
    "R_100": SymbolConfig(
        symbol="R_100",
        name="Volatility 100 Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    "R_75": SymbolConfig(
        symbol="R_75",
        name="Volatility 75 Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    "R_50": SymbolConfig(
        symbol="R_50",
        name="Volatility 50 Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    "R_25": SymbolConfig(
        symbol="R_25",
        name="Volatility 25 Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    "R_10": SymbolConfig(
        symbol="R_10",
        name="Volatility 10 Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    # 1Hz Volatility Indices
    "1HZ100V": SymbolConfig(
        symbol="1HZ100V",
        name="Volatility 100 (1s) Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    "1HZ75V": SymbolConfig(
        symbol="1HZ75V",
        name="Volatility 75 (1s) Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    "1HZ50V": SymbolConfig(
        symbol="1HZ50V",
        name="Volatility 50 (1s) Index",
        category="Synthetic",
        min_stake=0.35,
        max_stake=50000,
        min_duration=5,
        max_duration=10,
        duration_unit="t",
        supports_ticks=True,
        supports_minutes=True,
        supports_days=False,
        pip_size=0.01
    ),
    # Forex/Commodities
    "frxXAUUSD": SymbolConfig(
        symbol="frxXAUUSD",
        name="Gold/USD",
        category="Commodities",
        min_stake=1.0,
        max_stake=50000,
        min_duration=1,
        max_duration=365,
        duration_unit="d",
        supports_ticks=False,
        supports_minutes=False,
        supports_days=True,
        pip_size=0.01
    ),
}

def get_symbol_config(symbol: str) -> Optional[SymbolConfig]:
    """Get configuration for a specific symbol"""
    return SYMBOLS.get(symbol)

def get_short_term_symbols() -> List[str]:
    """Get symbols that support tick-based trading"""
    return [s for s, c in SYMBOLS.items() if c.supports_ticks]

def get_long_term_symbols() -> List[str]:
    """Get symbols that only support daily trading"""
    return [s for s, c in SYMBOLS.items() if c.supports_days and not c.supports_ticks]

def get_all_symbols() -> List[str]:
    """Get all available symbols"""
    return list(SYMBOLS.keys())

def validate_duration_for_symbol(symbol: str, duration: int, unit: str) -> Optional[tuple]:
    """Validate if duration is compatible with symbol. Returns (duration, unit) tuple if valid, None otherwise"""
    config = get_symbol_config(symbol)
    if not config:
        return None
    
    if unit == 't' and not config.supports_ticks:
        return None
    if unit == 'm' and not config.supports_minutes:
        return None
    if unit == 'd' and not config.supports_days:
        return None
    
    if unit == config.duration_unit:
        if config.min_duration <= duration <= config.max_duration:
            return (duration, unit)
        return (config.min_duration, config.duration_unit)
    
    return (duration, unit)

def get_symbol_list_text() -> str:
    """Generate formatted symbol list for display"""
    lines = []
    
    # Group by category
    categories: Dict[str, List[SymbolConfig]] = {}
    for config in SYMBOLS.values():
        if config.category not in categories:
            categories[config.category] = []
        categories[config.category].append(config)
    
    for category, symbols in categories.items():
        lines.append(f"\n**{category}:**")
        for s in symbols:
            duration_info = f"{s.min_duration}-{s.max_duration} {s.duration_unit}"
            lines.append(f"  • {s.symbol}: {s.name} ({duration_info})")
    
    return "\n".join(lines)

def get_default_symbol() -> str:
    """Get default trading symbol"""
    return "R_100"

def get_default_duration(symbol: str) -> tuple:
    """Get default duration for a symbol (duration, unit)"""
    config = get_symbol_config(symbol)
    if config:
        return (config.min_duration, config.duration_unit)
    return (5, 't')
