"""
Trading Manager - Main trading orchestration with session management
100% Automatic Trading - User only controls stop
"""

import logging
import time
import json
import os
import threading
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from deriv_ws import DerivWebSocket
from strategy import MultiIndicatorStrategy, Signal
from ldp_strategy import LDPStrategy, LDPSignal
from tick_analyzer import TickAnalyzerStrategy, TickSignal
from entry_filter import EntryFilter, RiskLevel, FilterResult
from hybrid_money_manager import HybridMoneyManager, RiskLevel as MMRiskLevel
from analytics import TradingAnalytics, TradeEntry
from symbols import get_symbol_config, get_default_duration, validate_duration_for_symbol

logger = logging.getLogger(__name__)

class TradingState(Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"

class StrategyType(Enum):
    MULTI_INDICATOR = "MULTI_INDICATOR"
    LDP = "LDP"
    TICK_ANALYZER = "TICK_ANALYZER"
    TERMINAL = "TERMINAL"
    TICK_PICKER = "TICK_PICKER"
    DIGITPAD = "DIGITPAD"
    AMT = "AMT"
    SNIPER = "SNIPER"

@dataclass
class TradingConfig:
    """Trading session configuration"""
    symbol: str = "R_100"
    strategy: StrategyType = StrategyType.MULTI_INDICATOR
    base_stake: float = 1.0
    target_trades: int = 50
    duration: int = 5
    duration_unit: str = "t"
    risk_level: str = "MEDIUM"
    use_martingale: bool = True
    max_martingale_level: int = 5
    daily_loss_limit: float = 50.0
    take_profit: float = 10.0
    stop_loss: float = 25.0
    max_trades: int = 100
    payout_percent: float = 85.0
    auto_trade: bool = True  # Always auto trade by default


class TradingManager:
    """
    Main Trading Manager - 100% Automatic Trading
    
    Features:
    - Fully automatic trading - user only stops
    - Session management with configurable targets
    - Multi-strategy support
    - Adaptive Martingale System
    - Real-time position tracking
    - Trade journaling and analytics
    - Session recovery from crashes
    """
    
    RECOVERY_FILE = "logs/session_recovery.json"
    MAX_SESSION_LOSS_PCT = 0.20  # 20% of balance
    
    def __init__(self, ws: DerivWebSocket, config: TradingConfig = None):
        self.ws = ws
        self.state = TradingState.IDLE
        self.config: Optional[TradingConfig] = config
        
        # Strategy instances
        self.strategy = None
        self.entry_filter = EntryFilter()
        self.money_manager = HybridMoneyManager()
        self.analytics = TradingAnalytics()
        
        # Session state
        self.session_trades = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_profit = 0.0
        self.starting_balance = 0.0
        
        # Martingale state
        self.martingale_level = 0
        self.martingale_base_stake = 0.0
        self.cumulative_loss = 0.0
        
        # Active trade tracking
        self.active_trade: Optional[Dict] = None
        self.pending_result = False
        
        # Threading
        self._trade_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._auto_trade_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self.on_trade_opened: Optional[Callable] = None
        self.on_trade_closed: Optional[Callable] = None
        self.on_session_complete: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_progress: Optional[Callable] = None
        
        # Last progress milestone for rate limiting
        self._last_progress_milestone = -1
        
        # If config provided, configure immediately
        if config:
            self.configure(config)
    
    def update_config(self, config: TradingConfig):
        """Update trading configuration"""
        self.config = config
        self.configure(config)
    
    def configure(self, config: TradingConfig):
        """Configure trading session"""
        self.config = config
        
        # Import strategies dynamically based on type
        if config.strategy in [StrategyType.MULTI_INDICATOR, StrategyType.TERMINAL]:
            self.strategy = MultiIndicatorStrategy(config.symbol)
        elif config.strategy in [StrategyType.LDP, StrategyType.DIGITPAD]:
            self.strategy = LDPStrategy(config.symbol)
        elif config.strategy in [StrategyType.TICK_ANALYZER, StrategyType.TICK_PICKER]:
            self.strategy = TickAnalyzerStrategy(config.symbol)
        elif config.strategy == StrategyType.AMT:
            # Accumulator uses multi-indicator base
            self.strategy = MultiIndicatorStrategy(config.symbol)
        elif config.strategy == StrategyType.SNIPER:
            # Sniper uses high confidence multi-indicator
            self.strategy = MultiIndicatorStrategy(config.symbol)
            self.strategy.min_confidence = 0.85  # Higher threshold for sniper
        else:
            self.strategy = MultiIndicatorStrategy(config.symbol)
        
        # Configure entry filter
        risk_map = {
            "LOW": RiskLevel.LOW,
            "MEDIUM": RiskLevel.MEDIUM,
            "HIGH": RiskLevel.HIGH,
            "AGGRESSIVE": RiskLevel.AGGRESSIVE
        }
        self.entry_filter.set_risk_level(risk_map.get(config.risk_level, RiskLevel.MEDIUM))
        
        # Configure money manager
        mm_risk_map = {
            "LOW": MMRiskLevel.LOW,
            "MEDIUM": MMRiskLevel.MEDIUM,
            "HIGH": MMRiskLevel.HIGH,
            "AGGRESSIVE": MMRiskLevel.VERY_HIGH
        }
        self.money_manager = HybridMoneyManager(
            base_stake=config.base_stake,
            risk_level=mm_risk_map.get(config.risk_level, MMRiskLevel.MEDIUM),
            daily_loss_limit=config.daily_loss_limit
        )
        
        logger.info(f"Trading configured: {config}")
    
    def start(self) -> bool:
        """Start automatic trading session"""
        if not self.config:
            logger.error("Trading not configured")
            return False
        
        if self.state == TradingState.RUNNING:
            logger.warning("Trading already running")
            return False
        
        if not self.ws.is_connected():
            logger.error("WebSocket not connected")
            return False
        
        # Initialize session
        self.starting_balance = self.ws.get_balance()
        self.session_trades = 0
        self.session_wins = 0
        self.session_losses = 0
        self.session_profit = 0.0
        self.martingale_level = 0
        self.martingale_base_stake = self.config.base_stake
        self.cumulative_loss = 0.0
        self._last_progress_milestone = -1
        
        # Start money manager session
        self.money_manager.start_session(self.starting_balance)
        self.analytics.start_session()
        
        # Subscribe to ticks
        self.ws.subscribe_ticks(self.config.symbol, self._on_tick)
        
        # Preload historical data to warm up strategy
        logger.info(f"Loading historical data for {self.config.symbol}...")
        if self.on_progress:
            self.on_progress({
                "type": "warmup",
                "message": "📊 Mengumpulkan data pasar...",
                "ticks_needed": 50
            })
        
        # Wait for history to load and preload strategy
        time.sleep(1)  # Give time for history to load
        history = self.ws.get_ticks_history(self.config.symbol, 100)
        if history:
            logger.info(f"Preloading {len(history)} historical ticks into strategy")
            for tick in history:
                # Add tick without generating signals during warmup
                if self.strategy:
                    self.strategy.add_tick(tick)
            logger.info(f"Strategy warmed up with {len(history)} ticks, ready to trade")
            if self.on_progress:
                self.on_progress({
                    "type": "warmup_complete",
                    "message": "✅ Data siap, mulai analisis...",
                    "ticks_loaded": len(history)
                })
        else:
            logger.warning("No historical ticks available, strategy will need to collect live data")
            if self.on_progress:
                self.on_progress({
                    "type": "warmup",
                    "message": "⏳ Mengumpulkan data live...",
                    "ticks_needed": 50
                })
        
        # Set callbacks for contract updates
        self.ws.on_contract_update = self._on_contract_update
        
        self.state = TradingState.RUNNING
        self._stop_event.clear()
        
        logger.info(
            f"Auto Trading started | Symbol: {self.config.symbol} | "
            f"Strategy: {self.config.strategy.value} | "
            f"Balance: {self.starting_balance:.2f}"
        )
        
        # Save recovery state
        self._save_recovery_state()
        
        return True
    
    def stop(self):
        """Stop trading session - Only control user has"""
        if self.state == TradingState.IDLE:
            return
        
        self.state = TradingState.STOPPING
        self._stop_event.set()
        
        # Unsubscribe from ticks
        if self.config:
            self.ws.unsubscribe_ticks(self.config.symbol)
        
        # Wait for any pending trade
        wait_count = 0
        while self.pending_result and wait_count < 30:
            time.sleep(1)
            wait_count += 1
        
        # Finalize session
        final_balance = self.ws.get_balance()
        self.session_profit = final_balance - self.starting_balance
        
        # End analytics session
        session_stats = self.analytics.end_session()
        
        logger.info(
            f"Trading stopped | Trades: {self.session_trades} | "
            f"Win Rate: {self._get_win_rate():.1f}% | "
            f"Profit: {self.session_profit:+.2f}"
        )
        
        # Trigger callback
        if self.on_session_complete:
            self.on_session_complete({
                "trades": self.session_trades,
                "wins": self.session_wins,
                "losses": self.session_losses,
                "profit": self.session_profit,
                "win_rate": self._get_win_rate(),
                "final_balance": final_balance
            })
        
        # Clear recovery file
        self._clear_recovery_state()
        
        self.state = TradingState.IDLE
    
    def _get_win_rate(self) -> float:
        if self.session_trades == 0:
            return 0.0
        return (self.session_wins / self.session_trades) * 100
    
    def get_status(self) -> Dict[str, Any]:
        """Get current trading status"""
        return {
            "state": self.state.value,
            "trades": self.session_trades,
            "session_trades": self.session_trades,
            "target_trades": self.config.target_trades if self.config else 50,
            "wins": self.session_wins,
            "losses": self.session_losses,
            "win_rate": self._get_win_rate(),
            "profit": self.session_profit,
            "session_profit": self.session_profit,
            "balance": self.ws.get_balance() if self.ws.is_connected() else 0,
            "martingale_level": self.martingale_level,
            "strategy": self.config.strategy.value if self.config else "N/A",
            "symbol": self.config.symbol if self.config else "N/A"
        }
    
    def _on_tick(self, tick: Dict[str, Any]):
        """Handle incoming tick data - Auto process signals"""
        if self.state != TradingState.RUNNING:
            logger.debug(f"Tick ignored - state is {self.state.value}")
            return
        
        if self.pending_result:
            logger.debug("Tick ignored - waiting for pending trade result")
            return  # Wait for current trade to complete
        
        if not self.strategy:
            logger.debug("Tick ignored - no strategy configured")
            return
        
        with self._trade_lock:
            # Add tick to strategy and get signal
            signal = self.strategy.add_tick(tick)
            
            if signal:
                logger.info(f"Signal received: direction={getattr(signal, 'direction', 'N/A')}, confidence={getattr(signal, 'confidence', 0):.2%}")
                self._process_signal(signal)
            else:
                logger.debug("No signal from strategy")
    
    def _process_signal(self, signal):
        """Process trading signal automatically"""
        if not self.config:
            logger.error("No config available for signal processing")
            return
        
        # Check session limits
        if self.config.max_trades and self.session_trades >= self.config.max_trades:
            logger.info("Max trades reached")
            self.stop()
            return
        
        # Check take profit
        if self.config.take_profit and self.session_profit >= self.config.take_profit:
            logger.info(f"Take profit reached: {self.session_profit:.2f}")
            self.stop()
            return
        
        # Check stop loss
        if self.config.stop_loss and self.session_profit <= -self.config.stop_loss:
            logger.info(f"Stop loss reached: {self.session_profit:.2f}")
            self.stop()
            return
        
        # Check session loss limit
        current_balance = self.ws.get_balance()
        session_loss = self.starting_balance - current_balance
        max_loss = self.starting_balance * self.MAX_SESSION_LOSS_PCT
        
        if session_loss >= max_loss:
            logger.warning(f"Session loss limit reached: {session_loss:.2f}")
            self.stop()
            return
        
        # Build market context for entry filter
        if hasattr(signal, 'indicators'):
            market_context = self.entry_filter.get_market_context(signal.indicators)
        else:
            market_context = {
                "trend": "NEUTRAL",
                "adx": 20,
                "volatility_percentile": 50
            }
        
        # Filter signal
        signal_data = {
            "confidence": signal.confidence,
            "direction": signal.direction if hasattr(signal, 'direction') else "BUY"
        }
        
        filter_result = self.entry_filter.filter(signal_data, market_context)
        
        if not filter_result.passed:
            logger.debug(f"Signal filtered: {filter_result.reasons}")
            return
        
        # Calculate stake
        stake = self._calculate_stake(filter_result)
        
        if stake <= 0:
            logger.warning("Stake calculation returned 0")
            return
        
        # Execute trade automatically
        self._execute_trade(signal, stake)
    
    def _calculate_stake(self, filter_result: FilterResult) -> float:
        """Calculate stake amount"""
        base_stake = self.money_manager.calculate_stake()
        
        if base_stake <= 0:
            return 0
        
        # Apply filter adjustments
        if "stake_reduction" in filter_result.adjustments:
            base_stake *= filter_result.adjustments["stake_reduction"]
        elif "stake_increase" in filter_result.adjustments:
            base_stake *= filter_result.adjustments["stake_increase"]
        
        # Martingale adjustment if enabled
        if self.config and self.config.use_martingale and self.martingale_level > 0:
            multiplier = 2.0 ** self.martingale_level
            base_stake = self.martingale_base_stake * multiplier
        
        # Ensure within limits
        balance = self.ws.get_balance()
        max_stake = balance * 0.20  # Max 20% of balance
        base_stake = min(base_stake, max_stake)
        base_stake = max(base_stake, 0.35)  # Min stake
        
        return base_stake
    
    def _calculate_next_stake(self) -> float:
        """Calculate next stake for display"""
        if not self.config:
            return 1.0
        if self.config.use_martingale and self.martingale_level > 0:
            return self.config.base_stake * (2.0 ** self.martingale_level)
        return self.config.base_stake
    
    def _execute_trade(self, signal, stake: float):
        """Execute a trade"""
        if not self.config:
            logger.error("No config available for trade execution")
            return
        
        try:
            logger.info(f"Executing trade with stake ${stake:.2f}")
            
            # Determine contract type based on signal
            if hasattr(signal, 'contract_type'):
                contract_type = signal.contract_type
            elif hasattr(signal, 'direction'):
                contract_type = "CALL" if signal.direction in ["UP", "BUY", "CALL"] else "PUT"
            else:
                contract_type = "CALL"  # Default
            
            logger.info(f"Contract type: {contract_type}")
            
            # Get duration
            duration = self.config.duration
            duration_unit = self.config.duration_unit
            
            # Validate duration for symbol
            validated_duration = validate_duration_for_symbol(
                self.config.symbol, duration, duration_unit
            )

            if validated_duration:
                duration, duration_unit = validated_duration
            else:
                logger.warning(
                    f"Invalid duration ({duration} {duration_unit}) for {self.config.symbol}. "
                    f"Using default."
                )
                duration, duration_unit = get_default_duration(self.config.symbol)
            
            # Place the trade
            self.pending_result = True
            
            result = self.ws.buy_contract(
                symbol=self.config.symbol,
                contract_type=contract_type,
                stake=stake,
                duration=duration,
                duration_unit=duration_unit
            )
            
            if result and result.get("contract_id"):
                self.active_trade = {
                    "contract_id": result["contract_id"],
                    "buy_price": result["buy_price"],
                    "contract_type": contract_type,
                    "stake": stake,
                    "entry_time": datetime.now(),
                    "trade_number": self.session_trades + 1,
                    "symbol": self.config.symbol
                }
                
                logger.info(
                    f"Trade opened | Type: {contract_type} | "
                    f"Stake: {stake:.2f} | Confidence: {signal.confidence:.1%}"
                )
                
                if self.on_trade_opened:
                    logger.debug(f"Triggering on_trade_opened callback: contract_id={result['contract_id']}")
                    self.on_trade_opened(self.active_trade)
            else:
                self.pending_result = False
                logger.error(f"Failed to open trade: {result}")
                
        except Exception as e:
            self.pending_result = False
            logger.error(f"Error executing trade: {e}")
            if self.on_error:
                self.on_error(str(e))
    
    def _on_contract_update(self, contract: Dict[str, Any]):
        """Handle contract status updates"""
        if not self.active_trade:
            return
        
        if not self.config:
            logger.error("No config available for contract update")
            return
        
        status = contract.get("status")
        is_sold = contract.get("is_sold", 0)
        
        is_closed = is_sold == 1 or status in ["sold", "won", "lost"]
        logger.debug(f"Contract update: status={status}, is_sold={is_sold}, is_closed={is_closed}")
        
        if is_closed:
            profit = contract.get("profit", 0)
            
            # Get balance before recording
            balance_before = self.ws.get_balance() if self.ws else 0
            
            # Update session stats
            self.session_trades += 1
            self.session_profit += profit
            
            if profit > 0:
                self.session_wins += 1
                # Reset martingale on win
                self.martingale_level = 0
                self.cumulative_loss = 0
            else:
                self.session_losses += 1
                # Increase martingale on loss
                if self.config.use_martingale:
                    self.cumulative_loss += abs(profit)
                    if self.martingale_level < self.config.max_martingale_level:
                        self.martingale_level += 1
            
            # Get balance after
            balance_after = self.ws.get_balance() if self.ws else balance_before + profit
            
            # Map contract type to direction
            contract_type = self.active_trade.get("contract_type", "CALL")
            direction = "BUY" if contract_type in ["CALL", "DIGITOVER", "DIGITEVEN"] else "SELL"
            
            # Record in analytics with all required fields
            now = datetime.now()
            trade_entry = TradeEntry(
                date=now.strftime("%Y-%m-%d"),
                time=now.strftime("%H:%M:%S"),
                symbol=self.config.symbol,
                direction=direction,
                entry_price=float(contract.get("entry_spot", 0)),
                exit_price=float(contract.get("exit_tick", 0)),
                stake=self.active_trade.get("stake", 0),
                payout=profit + self.active_trade.get("stake", 0) if profit > 0 else 0,
                profit=profit,
                result="WIN" if profit > 0 else "LOSS",
                martingale_level=self.martingale_level,
                balance_before=balance_before,
                balance_after=balance_after,
                win_rate=self._get_win_rate(),
                strategy=self.config.strategy.value if self.config.strategy else "UNKNOWN",
                confidence=0.7,  # Default confidence
                confluence=50.0  # Default confluence
            )
            self.analytics.record_trade(trade_entry)
            
            # Update money manager
            self.money_manager.record_trade(profit > 0)
            
            logger.info(
                f"Trade closed | Result: {'WIN' if profit > 0 else 'LOSS'} | "
                f"Profit: {profit:+.2f} | Session: {self.session_profit:+.2f}"
            )
            
            if self.on_trade_closed:
                callback_data = {
                    "profit": profit,
                    "session_profit": self.session_profit,
                    "trades": self.session_trades,
                    "wins": self.session_wins,
                    "losses": self.session_losses,
                    "win_rate": self._get_win_rate(),
                    "balance": balance_after,
                    "stake": self.active_trade.get("stake", 0),
                    "contract_type": self.active_trade.get("contract_type", ""),
                    "symbol": self.config.symbol if self.config else "",
                    "martingale_level": self.martingale_level,
                    "next_stake": self._calculate_next_stake(),
                    "entry_spot": float(contract.get("entry_spot", 0)),
                    "exit_tick": float(contract.get("exit_tick", 0))
                }
                logger.debug(f"Triggering on_trade_closed callback: profit={profit}, trades={self.session_trades}")
                self.on_trade_closed(callback_data)
            
            # Progress notification
            self._notify_progress()
            
            # Clear active trade
            self.active_trade = None
            self.pending_result = False
            
            # Save recovery state
            self._save_recovery_state()
    
    def _notify_progress(self):
        """Notify progress at milestones"""
        if not self.on_progress:
            return
        
        # Notify every 10 trades
        milestone = self.session_trades // 10
        if milestone > self._last_progress_milestone:
            self._last_progress_milestone = milestone
            self.on_progress({
                "trades": self.session_trades,
                "wins": self.session_wins,
                "losses": self.session_losses,
                "profit": self.session_profit,
                "win_rate": self._get_win_rate()
            })
    
    def _save_recovery_state(self):
        """Save state for crash recovery"""
        if not self.config:
            return
        
        try:
            os.makedirs("logs", exist_ok=True)
            state = {
                "config": {
                    "symbol": self.config.symbol,
                    "strategy": self.config.strategy.value if self.config.strategy else "UNKNOWN",
                    "base_stake": self.config.base_stake,
                    "use_martingale": self.config.use_martingale
                },
                "session": {
                    "trades": self.session_trades,
                    "wins": self.session_wins,
                    "losses": self.session_losses,
                    "profit": self.session_profit,
                    "starting_balance": self.starting_balance,
                    "martingale_level": self.martingale_level
                },
                "timestamp": datetime.now().isoformat()
            }
            with open(self.RECOVERY_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Failed to save recovery state: {e}")
    
    def _clear_recovery_state(self):
        """Clear recovery file"""
        try:
            if os.path.exists(self.RECOVERY_FILE):
                os.remove(self.RECOVERY_FILE)
        except:
            pass
    
    def recover_session(self) -> bool:
        """Attempt to recover from previous session"""
        try:
            if not os.path.exists(self.RECOVERY_FILE):
                return False
            
            with open(self.RECOVERY_FILE, 'r') as f:
                state = json.load(f)
            
            # Restore session stats
            session = state.get("session", {})
            self.session_trades = session.get("trades", 0)
            self.session_wins = session.get("wins", 0)
            self.session_losses = session.get("losses", 0)
            self.session_profit = session.get("profit", 0)
            self.starting_balance = session.get("starting_balance", 0)
            self.martingale_level = session.get("martingale_level", 0)
            
            logger.info(f"Session recovered: {self.session_trades} trades, {self.session_profit:+.2f} profit")
            return True
            
        except Exception as e:
            logger.error(f"Failed to recover session: {e}")
            return False
