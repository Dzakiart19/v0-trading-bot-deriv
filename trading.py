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
from accumulator_strategy import AccumulatorStrategy, AccumulatorSignal
from terminal_strategy import TerminalStrategy, TerminalSignal
from tick_picker_strategy import TickPickerStrategy, TickPickerSignal
from digitpad_strategy import DigitPadStrategy, DigitSignal
from sniper_strategy import SniperStrategy, SniperSignal
from entry_filter import EntryFilter, RiskLevel, FilterResult
from hybrid_money_manager import HybridMoneyManager, RiskLevel as MMRiskLevel, RecoveryMode
from analytics import TradingAnalytics, TradeEntry
from symbols import get_symbol_config, get_default_duration, validate_duration_for_symbol
from performance_monitor import performance_monitor
from user_preferences import user_preferences

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
    unlimited_trades: bool = False  # For demo testing - no trade limit


class TradingManager:
    """
    Main Trading Manager - 100% Automatic Trading
    
    Features:
    - Fully automatic trading - user only stops
    - Session management with configurable targets
    - Multi-strategy support
    - Fibonacci-based recovery system
    - Real-time position tracking
    - Trade journaling and analytics
    - Session recovery from crashes
    - Dynamic session loss limit calculation
    - Trade history analysis and pattern detection
    - Performance monitoring
    """
    
    RECOVERY_FILE = "logs/session_recovery.json"
    
    # Strategy-specific loss limits (percentage of starting balance)
    STRATEGY_LOSS_LIMITS = {
        "AMT": 0.30,           # 30% for accumulator (needs more room)
        "SNIPER": 0.15,        # 15% for sniper (more selective)
        "TERMINAL": 0.20,      # 20% default
        "TICK_PICKER": 0.20,
        "DIGITPAD": 0.25,      # 25% for digit trades
        "LDP": 0.25,
        "MULTI_INDICATOR": 0.20,
    }
    DEFAULT_SESSION_LOSS_PCT = 0.20  # 20% default
    
    def __init__(self, ws: DerivWebSocket, config: Optional[TradingConfig] = None):
        self.ws = ws
        self.state = TradingState.IDLE
        self.config: Optional[TradingConfig] = config
        
        # Strategy instances
        self.strategy = None
        self.entry_filter = EntryFilter()
        self.money_manager = HybridMoneyManager(recovery_mode=RecoveryMode.FIBONACCI)
        self.analytics = TradingAnalytics()
        
        # Dynamic session loss limit
        self.session_loss_limit = 0.0
        
        # Loss warning callback
        self.on_loss_warning: Optional[Callable] = None
        
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
        self._watchdog_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self.on_trade_opened: Optional[Callable] = None
        self.on_trade_closed: Optional[Callable] = None
        self.on_session_complete: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        self.on_progress: Optional[Callable] = None
        self.on_timeout_warning: Optional[Callable] = None
        
        # Last progress milestone for rate limiting
        self._last_progress_milestone = -1
        
        # Timeout and watchdog tracking - optimized for faster recovery
        self._consecutive_timeouts = 0
        self._max_consecutive_timeouts = 5  # Increased from 3 to allow more retries
        self._last_trade_attempt = 0
        self._last_activity_time = 0
        self._watchdog_interval = 15  # Check every 15 seconds for faster detection
        self._stuck_threshold = 60  # Restart after 1 minute stuck (was 2 minutes)
        self._pending_trade_timeout = 45  # Clear pending_result after 45 seconds
        self._trading_paused_due_to_timeout = False
        self._recovery_attempts = 0
        self._max_recovery_attempts = 3
        
        # Trade count control (0 = unlimited for demo testing)
        self._target_trade_count = 0  # 0 means unlimited
        self._unlimited_mode = False
        
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
        
        # Route to correct strategy class based on type
        if config.strategy == StrategyType.MULTI_INDICATOR:
            self.strategy = MultiIndicatorStrategy(config.symbol)
        elif config.strategy == StrategyType.LDP:
            self.strategy = LDPStrategy(config.symbol)
        elif config.strategy == StrategyType.TICK_ANALYZER:
            self.strategy = TickAnalyzerStrategy(config.symbol)
        elif config.strategy == StrategyType.TERMINAL:
            self.strategy = TerminalStrategy(config.symbol)
        elif config.strategy == StrategyType.TICK_PICKER:
            self.strategy = TickPickerStrategy(config.symbol)
        elif config.strategy == StrategyType.DIGITPAD:
            self.strategy = DigitPadStrategy()  # No symbol in constructor
        elif config.strategy == StrategyType.AMT:
            self.strategy = AccumulatorStrategy()  # No symbol in constructor
        elif config.strategy == StrategyType.SNIPER:
            self.strategy = SniperStrategy(config.symbol)
            self.strategy.start_trading()  # Enable automatic trading for Sniper
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
                # Handle different add_tick() signatures based on strategy instance type
                if self.strategy and self.config:
                    if isinstance(self.strategy, (AccumulatorStrategy, DigitPadStrategy)):
                        self.strategy.add_tick(self.config.symbol, tick)
                    else:
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
        
        # Set callbacks for contract updates and connection status
        self.ws.on_contract_update = self._on_contract_update
        self.ws.on_connection_status = self._on_connection_status
        
        self.state = TradingState.RUNNING
        self._stop_event.clear()
        self._last_activity_time = time.time()
        self._trading_paused_due_to_timeout = False
        
        # Start watchdog timer
        self._start_watchdog()
        
        logger.info(
            f"Auto Trading started | Symbol: {self.config.symbol} | "
            f"Strategy: {self.config.strategy.value} | "
            f"Balance: {self.starting_balance:.2f}"
        )
        
        # Save recovery state
        self._save_recovery_state()
        
        return True
    
    def _start_watchdog(self):
        """Start watchdog thread to detect stuck state with progressive recovery"""
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return
        
        def watchdog_loop():
            while self.state == TradingState.RUNNING and not self._stop_event.is_set():
                try:
                    time.sleep(self._watchdog_interval)
                    
                    if self.state != TradingState.RUNNING:
                        break
                    
                    current_time = time.time()
                    inactive_time = current_time - self._last_activity_time
                    
                    # Check for stuck pending trade first
                    if self.pending_result and self._last_trade_attempt > 0:
                        pending_time = current_time - self._last_trade_attempt
                        if pending_time > self._pending_trade_timeout:
                            logger.warning(f"Watchdog: Pending trade stuck for {pending_time:.0f}s, clearing...")
                            self.pending_result = False
                            self.active_trade = None
                            self._last_activity_time = current_time
                            
                            if self.on_progress:
                                self.on_progress({
                                    "type": "pending_cleared",
                                    "message": f"⚠️ Trade pending dibersihkan setelah {int(pending_time)}s, melanjutkan..."
                                })
                            continue
                    
                    # Progressive recovery based on inactive time
                    if inactive_time > 30 and inactive_time <= self._stuck_threshold:
                        # After 30 seconds: check connection health
                        logger.info(f"Watchdog: Checking connection health after {inactive_time:.0f}s inactivity")
                        if self._check_and_resume_trading():
                            logger.info("Watchdog: Connection healthy, continuing...")
                            self._last_activity_time = time.time()
                    
                    elif inactive_time > self._stuck_threshold:
                        logger.warning(f"Watchdog: No trade activity for {inactive_time:.0f}s, restarting session...")
                        
                        if self.on_progress:
                            self.on_progress({
                                "type": "watchdog_restart",
                                "message": f"⚠️ Bot tidak aktif {int(inactive_time)}s, melakukan restart..."
                            })
                        
                        self._recovery_attempts += 1
                        
                        if self._recovery_attempts > self._max_recovery_attempts:
                            logger.error("Max recovery attempts reached, stopping trading")
                            if self.on_error:
                                self.on_error("Koneksi tidak stabil setelah beberapa percobaan. Silakan cek koneksi internet.")
                            self.stop()
                        else:
                            self._restart_trading_session()
                        
                except Exception as e:
                    logger.error(f"Watchdog error: {e}")
        
        self._watchdog_thread = threading.Thread(target=watchdog_loop, daemon=True)
        self._watchdog_thread.start()
        logger.info("Watchdog timer started (interval: 15s, threshold: 60s)")
    
    def _restart_trading_session(self):
        """Restart trading session after stuck detection with connection recovery"""
        try:
            if not self.config:
                return
            
            logger.info(f"Restarting trading session (attempt {self._recovery_attempts})")
            
            # Reset state
            self._last_activity_time = time.time()
            self._consecutive_timeouts = 0
            self._trading_paused_due_to_timeout = False
            self.pending_result = False
            self.active_trade = None
            
            if self.ws and hasattr(self.ws, '_consecutive_timeouts'):
                self.ws._consecutive_timeouts = 0
            
            if self.ws and self.config:
                # Step 1: Check connection health
                if hasattr(self.ws, 'check_connection_health'):
                    if not self.ws.check_connection_health():
                        logger.warning("Connection unhealthy, attempting reconnect...")
                        # Manual reconnect
                        self.ws.disconnect()
                        time.sleep(2)
                        if self.ws.connect():
                            # Re-authorize if we have token
                            if hasattr(self.ws, 'token') and self.ws.token:
                                self.ws.authorize(self.ws.token)
                
                # Step 2: Re-subscribe to ticks
                try:
                    self.ws.unsubscribe_ticks(self.config.symbol)
                except Exception:
                    pass
                
                time.sleep(1)
                
                # Step 3: Preload data and subscribe
                if hasattr(self.ws, 'preload_data'):
                    self.ws.preload_data(self.config.symbol, count=100)
                
                self.ws.subscribe_ticks(self.config.symbol, self._on_tick)
                
                if self.on_progress:
                    self.on_progress({
                        "type": "session_restarted",
                        "message": "✅ Sesi trading di-restart, melanjutkan trading..."
                    })
            
            logger.info("Trading session restarted by watchdog")
            
        except Exception as e:
            logger.error(f"Failed to restart trading session: {e}")
    
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
    
    def set_trade_count(self, count: int, unlimited: bool = False):
        """Set target trade count. Use 0 or unlimited=True for unlimited trading (demo testing)"""
        self._target_trade_count = count
        self._unlimited_mode = unlimited or count == 0
        if self.config:
            self.config.unlimited_trades = self._unlimited_mode
            if not self._unlimited_mode:
                self.config.max_trades = count
        logger.info(f"Trade count set to: {'UNLIMITED' if self._unlimited_mode else count}")
    
    def get_trade_count_status(self) -> Dict[str, Any]:
        """Get trade count status"""
        return {
            "current_trades": self.session_trades,
            "target_trades": self._target_trade_count,
            "unlimited_mode": self._unlimited_mode,
            "remaining": "∞" if self._unlimited_mode else max(0, self._target_trade_count - self.session_trades)
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get current trading status"""
        # CRITICAL FIX: Display "∞" for unlimited mode instead of falling back to 50
        if self._unlimited_mode:
            target_display = "∞"
        elif self._target_trade_count > 0:
            target_display = self._target_trade_count
        else:
            target_display = self.config.target_trades if self.config else 50
        
        return {
            "state": self.state.value,
            "trades": self.session_trades,
            "session_trades": self.session_trades,
            "target_trades": target_display,
            "unlimited_mode": self._unlimited_mode,
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
    
    def get_debug_info(self) -> Dict[str, Any]:
        """Get detailed debug information for troubleshooting"""
        ws_metrics = {}
        if self.ws and hasattr(self.ws, 'get_connection_metrics'):
            ws_metrics = self.ws.get_connection_metrics()
        
        return {
            "trading_state": self.state.value,
            "pending_result": self.pending_result,
            "active_trade": bool(self.active_trade),
            "consecutive_timeouts": self._consecutive_timeouts,
            "trading_paused": self._trading_paused_due_to_timeout,
            "last_activity_time": self._last_activity_time,
            "last_trade_attempt": self._last_trade_attempt,
            "session_stats": {
                "trades": self.session_trades,
                "wins": self.session_wins,
                "losses": self.session_losses,
                "profit": self.session_profit,
                "win_rate": self._get_win_rate()
            },
            "ws_connection": ws_metrics,
            "config": {
                "symbol": self.config.symbol if self.config else None,
                "strategy": self.config.strategy.value if self.config else None,
                "base_stake": self.config.base_stake if self.config else None
            }
        }
    
    def _on_tick(self, tick: Dict[str, Any]):
        """Handle incoming tick data - Auto process signals"""
        try:
            # Track tick receipt (safely convert to float)
            tick_quote = float(tick.get('quote', 0) or 0)
            tick_epoch = tick.get('epoch', 0)
            
            # Track tick count for stall detection
            if not hasattr(self, '_tick_counter'):
                self._tick_counter = 0
                self._last_tick_log_time = 0
            self._tick_counter += 1
            
            # Log sparingly at INFO: first tick, and every 5 minutes for heartbeat confirmation
            import time as _time
            current_time = _time.time()
            if self._tick_counter == 1:
                logger.info(f"📥 FIRST TICK received | Quote: {tick_quote:.5f} | Counter started")
            elif current_time - self._last_tick_log_time >= 300:  # Every 5 minutes
                logger.info(f"📥 TICK HEARTBEAT | Total: {self._tick_counter} ticks | Latest: {tick_quote:.5f}")
                self._last_tick_log_time = current_time
            else:
                logger.debug(f"📥 TICK #{self._tick_counter} | Quote: {tick_quote:.5f} | Epoch: {tick_epoch}")
            
            if self.state != TradingState.RUNNING:
                logger.debug(f"⏸️ Tick ignored - state is {self.state.value}")
                return
            
            self._last_activity_time = time.time()
            
            if self.pending_result:
                logger.debug("⏳ Tick ignored - waiting for pending trade result")
                self._last_activity_time = time.time()
                return  # Wait for current trade to complete
            
            if not self.strategy:
                logger.warning("❌ Tick ignored - no strategy configured")
                return
            
            # Log strategy info
            strategy_name = type(self.strategy).__name__
            strategy_ticks = 0
            prices_attr = getattr(self.strategy, 'prices', None)
            closes_attr = getattr(self.strategy, 'closes', None)
            tick_history_attr = getattr(self.strategy, 'tick_history', None)
            if prices_attr is not None:
                strategy_ticks = len(prices_attr)
            elif closes_attr is not None:
                strategy_ticks = len(closes_attr)
            elif tick_history_attr is not None:
                strategy_ticks = len(tick_history_attr)
            
            logger.debug(f"📊 Processing tick with {strategy_name} (data points: {strategy_ticks})")
            
            with self._trade_lock:
                # Add tick to strategy and get signal
                # Handle different add_tick() signatures based on strategy instance type
                try:
                    if isinstance(self.strategy, (AccumulatorStrategy, DigitPadStrategy)):
                        # AccumulatorStrategy and DigitPadStrategy take (symbol, tick)
                        symbol = self.config.symbol if self.config else "R_100"
                        signal = self.strategy.add_tick(symbol, tick)
                    else:
                        # Other strategies take (tick) only
                        signal = self.strategy.add_tick(tick)
                    
                    # Log analysis result - keep most at DEBUG level
                    if signal is None:
                        # Try to get more info about why no signal
                        cooldown_info = ""
                        in_cooldown = False
                        if hasattr(self.strategy, 'last_signal_time'):
                            elapsed = time.time() - self.strategy.last_signal_time
                            cooldown = getattr(self.strategy, 'signal_cooldown', 
                                             getattr(self.strategy, 'SIGNAL_COOLDOWN', 12))
                            if elapsed < cooldown:
                                cooldown_info = f" (cooldown: {elapsed:.1f}s/{cooldown}s)"
                                in_cooldown = True
                        
                        min_ticks = getattr(self.strategy, 'MIN_TICKS', 
                                          getattr(self.strategy, 'min_ticks', 50))
                        if strategy_ticks < min_ticks:
                            # Log warmup once at 50% and 100% completion
                            if strategy_ticks == min_ticks // 2:
                                logger.info(f"📈 Warmup 50%: {strategy_ticks}/{min_ticks} ticks{cooldown_info}")
                            elif strategy_ticks == min_ticks - 1:
                                logger.info(f"📈 Warmup complete: {min_ticks} ticks ready{cooldown_info}")
                            else:
                                logger.debug(f"📈 Warming up: {strategy_ticks}/{min_ticks}{cooldown_info}")
                        elif in_cooldown:
                            logger.debug(f"⏳ In cooldown{cooldown_info}")
                        else:
                            logger.debug(f"🔍 No signal - analyzing market")
                except Exception as strategy_error:
                    logger.error(f"Strategy add_tick error: {strategy_error}", exc_info=True)
                    signal = None
                
                if signal:
                    signal_type = type(signal).__name__
                    signal_dir = getattr(signal, 'direction', getattr(signal, 'contract_type', 'N/A'))
                    signal_conf = getattr(signal, 'confidence', 0)
                    signal_reason = getattr(signal, 'reason', 'N/A')
                    logger.info(f"🎯 SIGNAL RECEIVED | Type: {signal_type} | "
                               f"Direction: {signal_dir} | Confidence: {signal_conf:.2%}")
                    logger.info(f"📋 Signal reason: {signal_reason}")
                    self._process_signal(signal)
                    
        except Exception as e:
            logger.error(f"Error in _on_tick: {e}", exc_info=True)
    
    def _process_signal(self, signal):
        """Process trading signal automatically"""
        try:
            logger.info(f"📝 Processing signal: {type(signal).__name__}")
            
            if not self.config:
                logger.error("❌ No config available for signal processing")
                return
            
            # Check session limits (skip if unlimited mode is enabled)
            if not self._unlimited_mode and not self.config.unlimited_trades:
                if self.config.max_trades and self.session_trades >= self.config.max_trades:
                    logger.info(f"Max trades reached: {self.session_trades}/{self.config.max_trades}")
                    self.stop()
                    return
                if self._target_trade_count > 0 and self.session_trades >= self._target_trade_count:
                    logger.info(f"Target trades reached: {self.session_trades}/{self._target_trade_count}")
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
            
            # Check session loss limit - dynamically calculated
            current_balance = self.ws.get_balance()
            session_loss = self.starting_balance - current_balance
            
            # Calculate dynamic loss limit based on strategy
            strategy_name = self.config.strategy.value if self.config else "MULTI_INDICATOR"
            loss_pct = self.STRATEGY_LOSS_LIMITS.get(strategy_name, self.DEFAULT_SESSION_LOSS_PCT)
            max_loss = self.starting_balance * loss_pct
            self.session_loss_limit = max_loss
            
            # Send warnings at 50%, 75%, 90%
            loss_percentage = session_loss / max_loss if max_loss > 0 else 0
            if loss_percentage >= 0.90 and not hasattr(self, '_warned_90'):
                self._warned_90 = True
                if self.on_loss_warning:
                    self.on_loss_warning(90, session_loss, max_loss, current_balance)
                if self.on_progress:
                    self.on_progress({
                        "type": "loss_warning",
                        "message": f"⚠️ PERINGATAN: 90% dari batas loss tercapai (${session_loss:.2f}/${max_loss:.2f})"
                    })
            elif loss_percentage >= 0.75 and not hasattr(self, '_warned_75'):
                self._warned_75 = True
                if self.on_loss_warning:
                    self.on_loss_warning(75, session_loss, max_loss, current_balance)
                if self.on_progress:
                    self.on_progress({
                        "type": "loss_warning",
                        "message": f"⚠️ Peringatan: 75% dari batas loss tercapai (${session_loss:.2f}/${max_loss:.2f})"
                    })
            elif loss_percentage >= 0.50 and not hasattr(self, '_warned_50'):
                self._warned_50 = True
                if self.on_loss_warning:
                    self.on_loss_warning(50, session_loss, max_loss, current_balance)
            
            if session_loss >= max_loss:
                logger.warning(f"Session loss limit reached: {session_loss:.2f} >= {max_loss:.2f} ({loss_pct*100:.0f}% of balance)")
                if self.on_progress:
                    self.on_progress({
                        "type": "session_stopped",
                        "message": f"🛑 Sesi dihentikan: Batas loss {loss_pct*100:.0f}% tercapai (${session_loss:.2f})"
                    })
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
                logger.info(f"⏭️ Signal filtered out: {filter_result.reasons}")
                return
            
            logger.info("✅ Signal passed entry filter")
            
            # Calculate stake
            stake = self._calculate_stake(filter_result)
            logger.info(f"💰 Stake calculated: ${stake:.2f}")
            
            if stake <= 0:
                logger.warning("❌ Stake calculation returned 0 - skipping trade")
                return
            
            # Execute trade automatically
            logger.info(f"🚀 Initiating trade execution...")
            self._execute_trade(signal, stake)
            
        except Exception as e:
            logger.error(f"❌ Error in _process_signal: {e}", exc_info=True)
    
    def _calculate_stake(self, filter_result: FilterResult) -> float:
        """
        Calculate stake amount using HybridMoneyManager (Fibonacci-based recovery)
        
        NOTE: HybridMoneyManager handles all recovery logic (Fibonacci/Anti-Martingale)
        We only apply filter adjustments here, no more 2x martingale override
        """
        # Get stake from money manager (uses Fibonacci or configured recovery mode)
        base_stake = self.money_manager.calculate_stake()
        
        if base_stake <= 0:
            return 0
        
        # Apply filter adjustments only
        if "stake_reduction" in filter_result.adjustments:
            base_stake *= filter_result.adjustments["stake_reduction"]
        elif "stake_increase" in filter_result.adjustments:
            base_stake *= filter_result.adjustments["stake_increase"]
        
        # Ensure within limits (10% max as per requirements)
        balance = self.ws.get_balance()
        max_stake = balance * 0.10  # Max 10% of balance (reduced from 20%)
        base_stake = min(base_stake, max_stake)
        base_stake = max(base_stake, 0.35)  # Min stake
        
        return base_stake
    
    def _calculate_next_stake(self) -> float:
        """Calculate next stake for display using money manager"""
        if not self.config:
            return 1.0
        # Use money manager for next stake calculation (Fibonacci-based)
        return self.money_manager.calculate_stake()
    
    def _execute_trade(self, signal, stake: float):
        """Execute a trade in a separate thread to avoid blocking WebSocket"""
        if not self.config:
            logger.error("No config available for trade execution")
            return
        
        if self._trading_paused_due_to_timeout:
            logger.warning("Trading paused due to consecutive timeouts. Waiting for connection recovery...")
            if self._check_and_resume_trading():
                logger.info("Connection recovered, resuming trading")
            else:
                return
        
        # Set pending_result immediately to prevent duplicate trades
        self.pending_result = True
        self._last_trade_attempt = time.time()
        
        # Capture signal data for thread
        signal_confidence = signal.confidence if hasattr(signal, 'confidence') else 0.5
        
        # Determine contract type and parameters based on signal type
        contract_type = "CALL"
        barrier = None
        growth_rate = None
        
        # Handle AccumulatorSignal - use ACCU contract with growth rate
        if isinstance(signal, AccumulatorSignal):
            if signal.action != "ENTER":
                logger.debug(f"Accumulator signal action is {signal.action}, not ENTER - skipping")
                self.pending_result = False
                return
            contract_type = "ACCU"
            growth_rate = signal.growth_rate / 100.0  # Convert 1-5 to 0.01-0.05
            # Accumulator requires minimum stake of $1.00
            if stake < 1.0:
                logger.info(f"Adjusting stake from ${stake:.2f} to $1.00 (Accumulator minimum)")
                stake = 1.0
            logger.info(f"AMT Accumulator: growth_rate={signal.growth_rate}%, trend={signal.trend_strength}")
        
        # Handle LDP and DigitPad signals - use digit contracts
        elif isinstance(signal, LDPSignal):
            contract_type = signal.contract_type  # DIGITOVER, DIGITUNDER, DIGITMATCH, DIGITDIFF, DIGITEVEN, DIGITODD
            if signal.barrier is not None:
                barrier = str(signal.barrier)
            logger.info(f"LDP Strategy: {contract_type} barrier={barrier}")
        
        elif isinstance(signal, DigitSignal):
            contract_type = signal.contract_type
            if signal.digit is not None:
                barrier = str(signal.digit)
            logger.info(f"DigitPad Strategy: {contract_type} digit={barrier}")
        
        # Handle Terminal Strategy - high probability trades
        elif isinstance(signal, TerminalSignal):
            contract_type = "CALL" if signal.direction == "BUY" else "PUT"
            logger.info(f"Terminal Strategy: {contract_type} probability={signal.probability:.1%}")
        
        # Handle Tick Picker - pattern-based trading
        elif isinstance(signal, TickPickerSignal):
            contract_type = "CALL" if signal.direction == "BUY" else "PUT"
            logger.info(f"Tick Picker: {contract_type} pattern={signal.pattern} streak={signal.streak}")
        
        # Handle Sniper - ultra-selective trading
        elif isinstance(signal, SniperSignal):
            contract_type = "CALL" if signal.direction == "BUY" else "PUT"
            logger.info(f"Sniper Strategy: {contract_type} confirmations={signal.confirmations}")
        
        # Handle Tick Analyzer - pattern detection
        elif isinstance(signal, TickSignal):
            contract_type = "CALL" if signal.direction == "BUY" else "PUT"
            logger.info(f"Tick Analyzer: {contract_type} type={signal.signal_type}")
        
        # Handle Multi-Indicator and other strategies with direction
        elif hasattr(signal, 'contract_type'):
            contract_type = signal.contract_type
            if hasattr(signal, 'barrier') and signal.barrier is not None:
                barrier = str(signal.barrier)
        elif hasattr(signal, 'direction'):
            contract_type = "CALL" if signal.direction in ["UP", "BUY", "CALL"] else "PUT"
        
        # Run trade execution in a separate thread to avoid blocking WebSocket
        def trade_worker():
            try:
                self._execute_trade_worker(contract_type, stake, signal_confidence, barrier, growth_rate)
            except Exception as e:
                logger.error(f"Trade worker error: {e}")
                self.pending_result = False
                self._handle_trade_failure(signal, str(e))
        
        trade_thread = threading.Thread(target=trade_worker, daemon=True)
        trade_thread.start()
        logger.info(f"Trade execution started in separate thread for {contract_type}" + (f" barrier={barrier}" if barrier else ""))
    
    def _execute_trade_worker(self, contract_type: str, stake: float, signal_confidence: float, barrier: Optional[str] = None, growth_rate: Optional[float] = None):
        """Worker method that actually executes the trade (runs in separate thread)"""
        if not self.config:
            logger.error("❌ No config available in trade worker")
            self.pending_result = False
            return
        
        try:
            logger.info(f"📤 TRADE EXECUTION STARTED")
            logger.info(f"   Symbol: {self.config.symbol}")
            logger.info(f"   Contract: {contract_type}")
            logger.info(f"   Stake: ${stake:.2f}")
            logger.info(f"   Confidence: {signal_confidence:.1%}")
            if barrier:
                logger.info(f"   Barrier: {barrier}")
            if growth_rate:
                logger.info(f"   Growth Rate: {growth_rate*100:.1f}%")
            
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
            result = self.ws.buy_contract(
                symbol=self.config.symbol,
                contract_type=contract_type,
                stake=stake,
                duration=duration,
                duration_unit=duration_unit,
                barrier=barrier,
                growth_rate=growth_rate
            )
            
            if result and result.get("contract_id"):
                self._consecutive_timeouts = 0
                self._last_activity_time = time.time()
                
                # Get current tick price as fallback for entry_price
                current_tick_price = 0.0
                try:
                    tick_history = self.ws.get_ticks_history(self.config.symbol, 1)
                    if tick_history:
                        current_tick_price = tick_history[-1].get("quote", 0.0)
                except Exception as e:
                    logger.warning(f"Could not get current tick price: {e}")
                
                self.active_trade = {
                    "contract_id": result["contract_id"],
                    "buy_price": result["buy_price"],
                    "contract_type": contract_type,
                    "stake": stake,
                    "entry_time": datetime.now(),
                    "trade_number": self.session_trades + 1,
                    "symbol": self.config.symbol,
                    "entry_tick_price": current_tick_price  # Store for fallback
                }
                
                logger.info(
                    f"✅ TRADE OPENED | Contract: {result['contract_id']} | "
                    f"Type: {contract_type} | Stake: ${stake:.2f} | "
                    f"Confidence: {signal_confidence:.1%} | Entry: ${current_tick_price:.5f}"
                )
                
                if self.on_trade_opened:
                    logger.debug(f"Triggering on_trade_opened callback: contract_id={result['contract_id']}")
                    self.on_trade_opened(self.active_trade)
            else:
                self.pending_result = False
                self._handle_trade_failure_internal(contract_type)
                
        except Exception as e:
            self.pending_result = False
            logger.error(f"Error executing trade: {e}")
            self._handle_trade_failure_internal(contract_type, str(e))
    
    def _handle_trade_failure_internal(self, contract_type: str, error_msg: Optional[str] = None):
        """Handle trade execution failure (thread-safe version)"""
        self._consecutive_timeouts += 1
        
        logger.warning(f"Trade failed (consecutive failures: {self._consecutive_timeouts}/{self._max_consecutive_timeouts})")
        
        if self._consecutive_timeouts >= self._max_consecutive_timeouts:
            logger.warning(f"Multiple failures detected, attempting connection recovery...")
            
            if self._check_and_resume_trading():
                logger.info("Connection recovered after failures")
                self._consecutive_timeouts = 0
                return
            
            self._trading_paused_due_to_timeout = True
            logger.error(f"Trading paused after {self._consecutive_timeouts} consecutive failures")
            
            if self.on_progress:
                self.on_progress({
                    "type": "trading_paused",
                    "message": f"⚠️ Trading dijeda: {self._consecutive_timeouts}x gagal. Mencoba pemulihan otomatis..."
                })
            
            def recovery_task():
                time.sleep(5)
                if self._check_and_resume_trading():
                    logger.info("Automatic recovery successful")
                    if self.on_progress:
                        self.on_progress({
                            "type": "trading_resumed",
                            "message": "✅ Koneksi pulih, trading dilanjutkan!"
                        })
            
            threading.Thread(target=recovery_task, daemon=True).start()
            
            if self.on_error:
                self.on_error(f"Trading paused: {self._consecutive_timeouts} consecutive failures - attempting recovery")
        
        elif error_msg and self.on_error:
            self.on_error(error_msg)
    
    def _handle_trade_failure(self, signal, error_msg: Optional[str] = None):
        """Handle trade execution failure with smart recovery"""
        self._consecutive_timeouts += 1
        
        logger.warning(f"Trade failed (consecutive failures: {self._consecutive_timeouts}/{self._max_consecutive_timeouts})")
        
        if self._consecutive_timeouts >= self._max_consecutive_timeouts:
            logger.warning(f"Multiple failures detected, attempting connection recovery...")
            
            # Try to recover connection first before pausing
            if self._check_and_resume_trading():
                logger.info("Connection recovered after failures")
                self._consecutive_timeouts = 0
                return
            
            # If recovery failed, pause trading
            self._trading_paused_due_to_timeout = True
            logger.error(f"Trading paused after {self._consecutive_timeouts} consecutive failures")
            
            if self.on_progress:
                self.on_progress({
                    "type": "trading_paused",
                    "message": f"⚠️ Trading dijeda: {self._consecutive_timeouts}x gagal. Mencoba pemulihan otomatis..."
                })
            
            # Attempt automatic recovery in background
            import threading
            def recovery_task():
                time.sleep(5)  # Wait 5 seconds before retry
                if self._check_and_resume_trading():
                    logger.info("Automatic recovery successful")
                    if self.on_progress:
                        self.on_progress({
                            "type": "trading_resumed",
                            "message": "✅ Koneksi pulih, trading dilanjutkan!"
                        })
            
            threading.Thread(target=recovery_task, daemon=True).start()
            
            if self.on_error:
                self.on_error(f"Trading paused: {self._consecutive_timeouts} consecutive failures - attempting recovery")
        
        elif error_msg and self.on_error:
            self.on_error(error_msg)
    
    def _check_and_resume_trading(self) -> bool:
        """Check if connection is healthy and resume trading"""
        if not self.ws:
            return False
        
        try:
            if hasattr(self.ws, 'check_connection_health') and self.ws.check_connection_health():
                self._trading_paused_due_to_timeout = False
                self._consecutive_timeouts = 0
                
                if hasattr(self.ws, '_consecutive_timeouts'):
                    self.ws._consecutive_timeouts = 0
                
                if self.on_progress:
                    self.on_progress({
                        "type": "trading_resumed",
                        "message": "✅ Koneksi stabil, trading dilanjutkan!"
                    })
                
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking connection: {e}")
            return False
    
    def _on_connection_status(self, connected: bool):
        """Handle connection status changes for auto-recovery after reconnect"""
        if connected:
            logger.info("Connection status: CONNECTED")
            
            # If we were running when disconnected, resume trading
            if self.state == TradingState.RUNNING and self.config:
                logger.info("Reconnected while running - resuming trading session...")
                
                # Update tick callback (subscription is already handled by deriv_ws._handle_authorize)
                # Just ensure our callback is registered
                if hasattr(self.ws, '_tick_callbacks'):
                    self.ws._tick_callbacks[self.config.symbol] = self._on_tick
                    logger.info(f"Updated tick callback for {self.config.symbol}")
                
                # Reset timeout counters
                self._consecutive_timeouts = 0
                self._trading_paused_due_to_timeout = False
                self._last_activity_time = time.time()
                
                if self.on_progress:
                    self.on_progress({
                        "type": "reconnected",
                        "message": "✅ Koneksi pulih, trading dilanjutkan..."
                    })
        else:
            logger.warning("Connection status: DISCONNECTED")
            if self.on_progress:
                self.on_progress({
                    "type": "disconnected",
                    "message": "⚠️ Koneksi terputus, menunggu reconnect..."
                })
    
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
            # For digit contracts, calculate profit from sell_price for accuracy
            buy_price = self.active_trade.get("buy_price", 0)
            sell_price = float(contract.get("sell_price", 0) or 0)
            payout = float(contract.get("payout", 0) or 0)
            
            # Calculate profit: prefer sell_price - buy_price for digit contracts
            if sell_price > 0 and buy_price > 0:
                profit = sell_price - buy_price
            else:
                profit = contract.get("profit", 0)
            
            # Log profit calculation for verification
            logger.info(f"Profit calculation: buy_price=${buy_price:.2f}, sell_price=${sell_price:.2f}, "
                       f"payout=${payout:.2f}, profit_field=${contract.get('profit', 0)}, "
                       f"final_profit=${profit:.2f}")
            
            # Get balance before recording
            balance_before = self.ws.get_balance() if self.ws else 0
            
            # Update session stats
            self.session_trades += 1
            self.session_profit += profit
            
            is_win = profit > 0
            
            if is_win:
                self.session_wins += 1
            else:
                self.session_losses += 1
            
            # Get entry_price with fallback to stored tick price or buy_price
            entry_price_raw = float(contract.get("entry_spot", 0))
            if entry_price_raw == 0:
                # Fallback 1: Use stored entry tick price
                entry_price_raw = float(self.active_trade.get("entry_tick_price", 0))
            if entry_price_raw == 0:
                # Fallback 2: Use buy_price from active trade
                entry_price_raw = float(self.active_trade.get("buy_price", 0))
            
            # Get exit_price with fallback
            exit_price_raw = float(contract.get("exit_tick", 0))
            if exit_price_raw == 0:
                exit_price_raw = float(contract.get("current_spot", 0))
            
            logger.info(f"Trade prices: entry={entry_price_raw}, exit={exit_price_raw}")
            
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
                entry_price=entry_price_raw,  # Use corrected entry price
                exit_price=exit_price_raw,    # Use corrected exit price
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
            self.money_manager.record_trade(
                stake=self.active_trade.get("stake", 0),
                profit=profit,
                is_win=profit > 0
            )
            
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
                    "entry_spot": entry_price_raw,  # Use corrected entry price
                    "exit_tick": exit_price_raw      # Use corrected exit price
                }
                logger.info(f"📊 TRADE CLOSED | Result: {'✅ WIN' if profit > 0 else '❌ LOSS'} | "
                           f"Profit: ${profit:+.2f} | Session P/L: ${self.session_profit:+.2f} | "
                           f"Trade #{self.session_trades}")
                self.on_trade_closed(callback_data)
            
            # Progress notification
            self._notify_progress()
            
            # Clear active trade and update activity time
            self.active_trade = None
            self.pending_result = False
            self._last_activity_time = time.time()
            
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
