"""
Strategy Configuration - Konfigurasi stake dan trade count per strategi
Setiap strategi memiliki minimum stake dan kontrak yang berbeda
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class StrategyName(Enum):
    MULTI_INDICATOR = "MULTI_INDICATOR"
    LDP = "LDP"
    TICK_ANALYZER = "TICK_ANALYZER"
    TERMINAL = "TERMINAL"
    TICK_PICKER = "TICK_PICKER"
    DIGITPAD = "DIGITPAD"
    AMT = "AMT"
    SNIPER = "SNIPER"


@dataclass
class StakeOption:
    """Pilihan stake untuk trading"""
    value: float
    label: str
    is_default: bool = False


@dataclass
class TradeCountOption:
    """Pilihan jumlah trade"""
    value: int  # -1 untuk unlimited
    label: str
    is_default: bool = False


@dataclass
class StrategyConfig:
    """Konfigurasi lengkap untuk setiap strategi"""
    name: StrategyName
    display_name: str
    description: str
    contract_types: List[str]
    min_stake: float
    max_stake: float
    default_stake: float
    stake_options: List[StakeOption]
    trade_count_options: List[TradeCountOption]
    default_duration: int
    duration_unit: str
    needs_barrier: bool = False
    needs_growth_rate: bool = False
    default_growth_rate: float = 0.01
    supported_symbols: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name.value,
            "display_name": self.display_name,
            "description": self.description,
            "contract_types": self.contract_types,
            "min_stake": self.min_stake,
            "max_stake": self.max_stake,
            "default_stake": self.default_stake,
            "stake_options": [{"value": s.value, "label": s.label, "is_default": s.is_default} for s in self.stake_options],
            "trade_count_options": [{"value": t.value, "label": t.label, "is_default": t.is_default} for t in self.trade_count_options],
            "default_duration": self.default_duration,
            "duration_unit": self.duration_unit,
            "needs_barrier": self.needs_barrier,
            "needs_growth_rate": self.needs_growth_rate,
            "default_growth_rate": self.default_growth_rate,
            "supported_symbols": self.supported_symbols
        }


DEFAULT_SYMBOLS = [
    "R_100", "R_75", "R_50", "R_25", "R_10",
    "1HZ100V", "1HZ75V", "1HZ50V", "1HZ25V", "1HZ10V"
]

STANDARD_TRADE_COUNTS = [
    TradeCountOption(5, "5 Trades"),
    TradeCountOption(10, "10 Trades", is_default=True),
    TradeCountOption(20, "20 Trades"),
    TradeCountOption(50, "50 Trades"),
    TradeCountOption(100, "100 Trades"),
    TradeCountOption(-1, "Unlimited ♾️")
]


STRATEGY_CONFIGS: Dict[StrategyName, StrategyConfig] = {
    StrategyName.AMT: StrategyConfig(
        name=StrategyName.AMT,
        display_name="AMT Accumulator",
        description="Accumulator contract dengan growth rate. Target profit dari akumulasi bertahap.",
        contract_types=["ACCU"],
        min_stake=1.00,
        max_stake=100.00,
        default_stake=1.00,
        stake_options=[
            StakeOption(1.00, "$1.00", is_default=True),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
            StakeOption(20.00, "$20.00"),
            StakeOption(50.00, "$50.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=0,
        duration_unit="",
        needs_growth_rate=True,
        default_growth_rate=0.01,
        supported_symbols=["R_100", "R_75", "R_50", "R_25", "R_10",
                          "1HZ100V", "1HZ75V", "1HZ50V", "1HZ25V", "1HZ10V"]
    ),
    
    StrategyName.LDP: StrategyConfig(
        name=StrategyName.LDP,
        display_name="LDP Analyzer",
        description="Last Digit Prediction - Prediksi digit terakhir harga dengan analisis frekuensi.",
        contract_types=["DIGITOVER", "DIGITUNDER", "DIGITMATCH", "DIGITDIFF", "DIGITEVEN", "DIGITODD"],
        min_stake=0.35,
        max_stake=50.00,
        default_stake=0.50,
        stake_options=[
            StakeOption(0.35, "$0.35"),
            StakeOption(0.50, "$0.50", is_default=True),
            StakeOption(1.00, "$1.00"),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=5,
        duration_unit="t",
        needs_barrier=True,
        supported_symbols=DEFAULT_SYMBOLS
    ),
    
    StrategyName.TERMINAL: StrategyConfig(
        name=StrategyName.TERMINAL,
        display_name="Terminal Pro",
        description="Smart Analysis dengan 80% minimum probability. Multi-indicator weighting system.",
        contract_types=["CALL", "PUT"],
        min_stake=0.35,
        max_stake=100.00,
        default_stake=1.00,
        stake_options=[
            StakeOption(0.35, "$0.35"),
            StakeOption(0.50, "$0.50"),
            StakeOption(1.00, "$1.00", is_default=True),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
            StakeOption(25.00, "$25.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=5,
        duration_unit="t",
        supported_symbols=DEFAULT_SYMBOLS
    ),
    
    StrategyName.TICK_PICKER: StrategyConfig(
        name=StrategyName.TICK_PICKER,
        display_name="Tick Picker",
        description="Pattern analysis untuk Rise/Fall. Analisis trend dan momentum tick.",
        contract_types=["CALL", "PUT"],
        min_stake=0.35,
        max_stake=50.00,
        default_stake=0.50,
        stake_options=[
            StakeOption(0.35, "$0.35"),
            StakeOption(0.50, "$0.50", is_default=True),
            StakeOption(1.00, "$1.00"),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=5,
        duration_unit="t",
        supported_symbols=DEFAULT_SYMBOLS
    ),
    
    StrategyName.DIGITPAD: StrategyConfig(
        name=StrategyName.DIGITPAD,
        display_name="DigitPad",
        description="Digit frequency analysis dengan heatmap. Prediksi Even/Odd dan Differ/Match.",
        contract_types=["DIGITDIFF", "DIGITMATCH", "DIGITEVEN", "DIGITODD"],
        min_stake=0.35,
        max_stake=50.00,
        default_stake=0.50,
        stake_options=[
            StakeOption(0.35, "$0.35"),
            StakeOption(0.50, "$0.50", is_default=True),
            StakeOption(1.00, "$1.00"),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=5,
        duration_unit="t",
        needs_barrier=True,
        supported_symbols=DEFAULT_SYMBOLS
    ),
    
    StrategyName.SNIPER: StrategyConfig(
        name=StrategyName.SNIPER,
        display_name="Sniper",
        description="Ultra-selective high probability trading. Hanya entry saat confidence 80%+.",
        contract_types=["CALL", "PUT"],
        min_stake=0.50,
        max_stake=100.00,
        default_stake=1.00,
        stake_options=[
            StakeOption(0.50, "$0.50"),
            StakeOption(1.00, "$1.00", is_default=True),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
            StakeOption(25.00, "$25.00"),
            StakeOption(50.00, "$50.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=5,
        duration_unit="t",
        supported_symbols=DEFAULT_SYMBOLS
    ),
    
    StrategyName.TICK_ANALYZER: StrategyConfig(
        name=StrategyName.TICK_ANALYZER,
        display_name="Tick Analyzer",
        description="Analisis pola tick untuk Rise/Fall trading.",
        contract_types=["CALL", "PUT"],
        min_stake=0.35,
        max_stake=50.00,
        default_stake=0.50,
        stake_options=[
            StakeOption(0.35, "$0.35"),
            StakeOption(0.50, "$0.50", is_default=True),
            StakeOption(1.00, "$1.00"),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=5,
        duration_unit="t",
        supported_symbols=DEFAULT_SYMBOLS
    ),
    
    StrategyName.MULTI_INDICATOR: StrategyConfig(
        name=StrategyName.MULTI_INDICATOR,
        display_name="Multi-Indicator",
        description="Kombinasi RSI, MACD, EMA untuk konfirmasi sinyal trading.",
        contract_types=["CALL", "PUT"],
        min_stake=0.35,
        max_stake=50.00,
        default_stake=0.50,
        stake_options=[
            StakeOption(0.35, "$0.35"),
            StakeOption(0.50, "$0.50", is_default=True),
            StakeOption(1.00, "$1.00"),
            StakeOption(2.00, "$2.00"),
            StakeOption(5.00, "$5.00"),
            StakeOption(10.00, "$10.00"),
        ],
        trade_count_options=STANDARD_TRADE_COUNTS,
        default_duration=5,
        duration_unit="t",
        supported_symbols=DEFAULT_SYMBOLS
    ),
}


def get_strategy_config(strategy_name: str) -> Optional[StrategyConfig]:
    """Get strategy configuration by name"""
    try:
        name = StrategyName(strategy_name.upper())
        return STRATEGY_CONFIGS.get(name)
    except ValueError:
        return None


def get_all_strategy_configs() -> Dict[str, Dict[str, Any]]:
    """Get all strategy configurations as dict"""
    return {
        name.value: config.to_dict() 
        for name, config in STRATEGY_CONFIGS.items()
    }


def validate_stake(strategy_name: str, stake: float) -> tuple[bool, str]:
    """Validate stake amount for a strategy"""
    config = get_strategy_config(strategy_name)
    if not config:
        return False, f"Unknown strategy: {strategy_name}"
    
    if stake < config.min_stake:
        return False, f"Minimum stake for {config.display_name} is ${config.min_stake:.2f}"
    
    if stake > config.max_stake:
        return False, f"Maximum stake for {config.display_name} is ${config.max_stake:.2f}"
    
    return True, ""


def get_contract_type_for_strategy(strategy_name: str, signal) -> str:
    """
    Get appropriate contract type based on strategy and signal
    
    Args:
        strategy_name: Name of the strategy
        signal: Trading signal from strategy
    
    Returns:
        Contract type string (CALL, PUT, DIGITOVER, etc.)
    """
    config = get_strategy_config(strategy_name)
    if not config:
        return "CALL"
    
    if strategy_name.upper() == "AMT":
        return "ACCU"
    
    if strategy_name.upper() in ["LDP", "DIGITPAD"]:
        if hasattr(signal, 'contract_type'):
            return signal.contract_type
        return config.contract_types[0]
    
    if hasattr(signal, 'direction'):
        direction = signal.direction
        if direction in ["BUY", "CALL", "RISE"]:
            return "CALL"
        elif direction in ["SELL", "PUT", "FALL"]:
            return "PUT"
    
    return config.contract_types[0]


def get_barrier_for_strategy(strategy_name: str, signal) -> Optional[str]:
    """
    Get barrier value for digit contracts
    
    Args:
        strategy_name: Name of the strategy
        signal: Trading signal from strategy
    
    Returns:
        Barrier string or None
    """
    config = get_strategy_config(strategy_name)
    if not config or not config.needs_barrier:
        return None
    
    if hasattr(signal, 'barrier') and signal.barrier is not None:
        return str(signal.barrier)
    
    return "5"


def get_growth_rate_for_amt(signal=None) -> float:
    """Get growth rate for AMT Accumulator strategy"""
    if signal and hasattr(signal, 'growth_rate'):
        return signal.growth_rate / 100.0
    
    return 0.01
