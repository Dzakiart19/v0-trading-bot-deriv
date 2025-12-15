"""
Hybrid Money Manager - Fibonacci-based progressive recovery system with risk management
Enhanced with anti-martingale option and balance protection
IMPROVED: Absolute balance guard, breach state persistence, dynamic stake caps
"""

import json
import logging
import os
import random
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

BREACH_STATE_FILE = "logs/breach_state.json"


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class RecoveryMode(Enum):
    FIBONACCI = "FIBONACCI"      # 1, 1, 2, 3, 5, 8 - smooth recovery
    ANTI_MARTINGALE = "ANTI_MARTINGALE"  # Decrease after loss, increase after win
    FIXED = "FIXED"              # Always use base stake
    PROGRESSIVE = "PROGRESSIVE"   # Old martingale-like (not recommended)


@dataclass
class TradeRecord:
    """Record of a single trade"""
    stake: float
    profit: float
    is_win: bool
    level: int
    balance_before: float
    balance_after: float
    timestamp: float


@dataclass
class SessionMetrics:
    """Session trading metrics"""
    starting_balance: float
    current_balance: float
    peak_balance: float
    lowest_balance: float
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    total_profit: float = 0.0
    max_drawdown: float = 0.0
    deficit: float = 0.0
    recovery_level: int = 0


class HybridMoneyManager:
    """
    Hybrid Money Manager with Fibonacci-based Recovery
    
    Features:
    - Fibonacci sequence recovery (1, 1, 2, 3, 5, 8) - smoother than martingale
    - Anti-martingale option for conservative approach
    - Dynamic balance protection
    - Session loss limit with warnings at 50%, 75%
    - Strategy-specific loss limits
    - Maximum stake per trade = 10% of balance
    - Real-time balance tracking
    """
    
    # Fibonacci sequence for recovery
    FIBONACCI = [1, 1, 2, 3, 5, 8, 13, 21]
    
    # Risk configurations
    RISK_CONFIG = {
        RiskLevel.LOW: {"max_levels": 6, "max_stake_pct": 0.05},
        RiskLevel.MEDIUM: {"max_levels": 5, "max_stake_pct": 0.08},
        RiskLevel.HIGH: {"max_levels": 4, "max_stake_pct": 0.10},
        RiskLevel.VERY_HIGH: {"max_levels": 3, "max_stake_pct": 0.15}
    }
    
    # Strategy-specific loss limits (as percentage of starting balance)
    STRATEGY_LOSS_LIMITS = {
        "AMT": 0.30,           # 30% for accumulator (needs more room)
        "SNIPER": 0.15,        # 15% for sniper (more selective)
        "TERMINAL": 0.20,      # 20% default
        "TICK_PICKER": 0.20,
        "DIGITPAD": 0.25,      # 25% for digit trades
        "LDP": 0.25,
        "MULTI_INDICATOR": 0.20,
        "DEFAULT": 0.20
    }
    
    # Warning thresholds (percentage of loss limit reached)
    WARNING_THRESHOLDS = [0.50, 0.75, 0.90]
    
    # Absolute balance guard - stop if balance drops below this % of starting balance
    ABSOLUTE_BALANCE_GUARD_PCT = 0.10  # 10% of starting balance
    
    # Per-strategy hard stake ceilings (max stake regardless of recovery level)
    STRATEGY_STAKE_CEILINGS = {
        "AMT": 10.0,           # Max $10 for accumulator
        "SNIPER": 5.0,         # Max $5 for sniper
        "TERMINAL": 8.0,
        "TICK_PICKER": 8.0,
        "DIGITPAD": 10.0,
        "LDP": 10.0,
        "MULTI_INDICATOR": 8.0,
        "DEFAULT": 10.0
    }
    
    def __init__(
        self,
        base_stake: float = 1.0,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        daily_loss_limit: float = 50.0,
        profit_target: float = 0.0,
        recovery_mode: RecoveryMode = RecoveryMode.FIBONACCI,
        strategy_name: str = "DEFAULT"
    ):
        self.base_stake = base_stake
        self.risk_level = risk_level
        self.daily_loss_limit = daily_loss_limit
        self.profit_target = profit_target
        self.recovery_mode = recovery_mode
        self.strategy_name = strategy_name
        
        # Get risk config
        config = self.RISK_CONFIG[risk_level]
        self.max_levels = config["max_levels"]
        self.max_stake_pct = config["max_stake_pct"]
        
        # Session state
        self.metrics: Optional[SessionMetrics] = None
        self.trade_history: deque = deque(maxlen=200)
        self.is_recovering = False
        
        # Warning callbacks
        self.on_loss_warning: Optional[Callable[[float, float, float, float], None]] = None
        self.on_pause_trading: Optional[Callable[[str], None]] = None
        self.on_resume_trading: Optional[Callable[[], None]] = None
        self.warnings_sent: List[float] = []
        
        # Last balance check
        self._last_balance_check = 0
        self._cached_balance = 0.0
        self._balance_check_interval = 10  # seconds
        
        # Breach state tracking
        self._breach_triggered = False
        self._breach_reason = ""
        
        # Pause state tracking (recoverable pause, not breach)
        self._pause_triggered = False
        self._pause_reason = ""
        self._pause_start_time = 0.0
        self._pause_cooldown = 60.0  # 60 second cooldown after consecutive losses
        self._consecutive_loss_limit = 3  # Pause after 3 consecutive losses
        
        # Load any persisted breach state
        self._load_breach_state()
    
    def start_session(self, starting_balance: float, strategy_name: Optional[str] = None) -> None:
        """Initialize a new trading session"""
        if strategy_name:
            self.strategy_name = strategy_name
        
        self.metrics = SessionMetrics(
            starting_balance=starting_balance,
            current_balance=starting_balance,
            peak_balance=starting_balance,
            lowest_balance=starting_balance
        )
        self.trade_history.clear()
        self.is_recovering = False
        self.warnings_sent = []
        self._cached_balance = starting_balance
        
        # Calculate actual loss limit based on strategy
        loss_limit_pct = self.STRATEGY_LOSS_LIMITS.get(
            self.strategy_name, 
            self.STRATEGY_LOSS_LIMITS["DEFAULT"]
        )
        self.session_loss_limit = starting_balance * loss_limit_pct
        
        # Calculate absolute balance guard threshold
        self.absolute_guard_balance = starting_balance * self.ABSOLUTE_BALANCE_GUARD_PCT
        
        # Get strategy stake ceiling
        self.stake_ceiling = self.STRATEGY_STAKE_CEILINGS.get(
            self.strategy_name,
            self.STRATEGY_STAKE_CEILINGS["DEFAULT"]
        )
        
        # Check if breach state was previously triggered
        if self._breach_triggered:
            logger.warning(f"Previous breach state detected: {self._breach_reason}")
        
        logger.info(
            f"Session started | Balance: {starting_balance:.2f} | "
            f"Risk: {self.risk_level.value} | Base stake: {self.base_stake:.2f} | "
            f"Recovery: {self.recovery_mode.value} | "
            f"Loss limit: {self.session_loss_limit:.2f} ({loss_limit_pct*100:.0f}%) | "
            f"Absolute guard: {self.absolute_guard_balance:.2f} | "
            f"Stake ceiling: {self.stake_ceiling:.2f}"
        )
    
    def update_balance(self, current_balance: float):
        """Update cached balance for real-time tracking"""
        self._cached_balance = current_balance
        self._last_balance_check = time.time()
        
        if self.metrics:
            self.metrics.current_balance = current_balance
    
    def should_refresh_balance(self) -> bool:
        """Check if balance should be refreshed"""
        return time.time() - self._last_balance_check > self._balance_check_interval
    
    def calculate_stake(self) -> float:
        """
        Calculate next stake amount using Fibonacci or Anti-Martingale
        
        Returns:
            Recommended stake amount (0 if should stop)
        """
        if not self.metrics:
            return self.base_stake
        
        balance = self.metrics.current_balance
        
        # Check breach state first - if triggered, stop trading
        if self._breach_triggered:
            logger.warning(f"Trading blocked - breach state active: {self._breach_reason}")
            return 0
        
        # ABSOLUTE BALANCE GUARD - Critical safety check
        if balance < self.absolute_guard_balance:
            self._trigger_breach(
                f"Absolute balance guard triggered: ${balance:.2f} < ${self.absolute_guard_balance:.2f} (10% of starting)"
            )
            return 0
        
        # Check if we should stop (session loss limit)
        if self._check_session_loss_exceeded():
            self._trigger_breach("Session loss limit reached")
            return 0
        
        # Check minimum balance threshold
        min_balance_threshold = self.base_stake * 2
        if balance < min_balance_threshold:
            logger.warning(f"Balance ({balance:.2f}) below minimum threshold ({min_balance_threshold:.2f})")
            return 0
        
        # Calculate stake based on recovery mode
        if self.recovery_mode == RecoveryMode.FIBONACCI:
            stake = self._calculate_fibonacci_stake()
        elif self.recovery_mode == RecoveryMode.ANTI_MARTINGALE:
            stake = self._calculate_anti_martingale_stake()
        elif self.recovery_mode == RecoveryMode.FIXED:
            stake = self.base_stake
        else:
            stake = self._calculate_progressive_stake()
        
        # Apply max stake limit (10% of balance)
        max_stake = balance * self.max_stake_pct
        stake = min(stake, max_stake)
        
        # Minimum stake
        stake = max(stake, 0.35)
        
        # Apply strategy-specific stake ceiling
        stake = min(stake, self.stake_ceiling)
        
        # Dynamic stake cap based on current win rate (reduce stake if losing)
        if self.metrics.total_trades >= 5:
            win_rate = self.metrics.wins / self.metrics.total_trades
            if win_rate < 0.4:  # Less than 40% win rate
                stake = min(stake, self.base_stake)  # Cap at base stake
                logger.debug(f"Win rate cap applied: {win_rate*100:.1f}% -> stake capped to base")
        
        # Final balance check
        if stake > balance * 0.5:
            stake = balance * 0.1  # Reduce to 10% if stake is too large
        
        logger.debug(f"Calculated stake: {stake:.2f} (mode: {self.recovery_mode.value})")
        return stake
    
    def _calculate_fibonacci_stake(self) -> float:
        """Calculate stake using Fibonacci sequence - smoother than martingale"""
        if not self.metrics or self.metrics.deficit <= 0:
            self.is_recovering = False
            return self.base_stake
        
        self.is_recovering = True
        level = min(self.metrics.recovery_level, len(self.FIBONACCI) - 1)
        
        if level >= self.max_levels:
            logger.warning(f"Max Fibonacci level ({self.max_levels}) reached, resetting")
            self.metrics.deficit = 0
            self.metrics.recovery_level = 0
            self.is_recovering = False
            return self.base_stake
        
        # Fibonacci multiplier
        fib_multiplier = self.FIBONACCI[level]
        stake = self.base_stake * fib_multiplier
        
        logger.debug(
            f"Fibonacci stake: {stake:.2f} | Level: {level + 1}/{self.max_levels} | "
            f"Multiplier: {fib_multiplier} | Deficit: {self.metrics.deficit:.2f}"
        )
        
        return stake
    
    def _calculate_anti_martingale_stake(self) -> float:
        """
        Anti-Martingale: Decrease stake after loss, increase after win
        Much safer for small balances
        """
        if not self.metrics:
            return self.base_stake
        
        # After a win, increase slightly
        if self.metrics.consecutive_wins > 0:
            multiplier = min(1.0 + (self.metrics.consecutive_wins * 0.1), 1.5)
            return self.base_stake * multiplier
        
        # After a loss, decrease stake
        if self.metrics.consecutive_losses > 0:
            multiplier = max(0.5, 1.0 - (self.metrics.consecutive_losses * 0.1))
            return self.base_stake * multiplier
        
        return self.base_stake
    
    def _calculate_progressive_stake(self) -> float:
        """Old progressive/martingale calculation (less recommended)"""
        if not self.metrics or self.metrics.deficit <= 0:
            self.is_recovering = False
            return self.base_stake
        
        self.is_recovering = True
        level = self.metrics.recovery_level
        
        if level >= self.max_levels:
            self.metrics.deficit = 0
            self.metrics.recovery_level = 0
            self.is_recovering = False
            return self.base_stake
        
        # Progressive with softer multiplier (1.5x instead of 2x)
        exponent = 1 + (level * 0.3)
        stake = self.base_stake * (1.5 ** exponent)
        
        return stake
    
    def record_trade(self, stake: float, profit: float, is_win: bool):
        """
        Record trade result and update state
        
        Args:
            stake: Stake amount used
            profit: Profit/loss from trade
            is_win: Whether trade was won
        """
        if not self.metrics:
            return
        
        balance_before = self.metrics.current_balance
        balance_after = balance_before + profit
        
        # Create trade record
        record = TradeRecord(
            stake=stake,
            profit=profit,
            is_win=is_win,
            level=self.metrics.recovery_level,
            balance_before=balance_before,
            balance_after=balance_after,
            timestamp=time.time()
        )
        self.trade_history.append(record)
        
        # Update metrics
        self.metrics.current_balance = balance_after
        self.metrics.total_trades += 1
        self.metrics.total_profit += profit
        
        if is_win:
            self.metrics.wins += 1
            self.metrics.consecutive_wins += 1
            self.metrics.consecutive_losses = 0
            self.metrics.max_consecutive_wins = max(
                self.metrics.max_consecutive_wins,
                self.metrics.consecutive_wins
            )
            
            # Recovery success
            if self.is_recovering:
                self.metrics.deficit = max(0, self.metrics.deficit - profit)
                
                if self.metrics.deficit <= 0:
                    logger.info("Recovery complete!")
                    self.metrics.recovery_level = 0
                    self.is_recovering = False
                else:
                    # Partial recovery - reduce level but keep deficit
                    self.metrics.recovery_level = max(0, self.metrics.recovery_level - 1)
        else:
            self.metrics.losses += 1
            self.metrics.consecutive_losses += 1
            self.metrics.consecutive_wins = 0
            self.metrics.max_consecutive_losses = max(
                self.metrics.max_consecutive_losses,
                self.metrics.consecutive_losses
            )
            
            # Add to deficit
            self.metrics.deficit += abs(profit)
            self.metrics.recovery_level += 1
        
        # Update peak and lowest
        self.metrics.peak_balance = max(self.metrics.peak_balance, balance_after)
        self.metrics.lowest_balance = min(self.metrics.lowest_balance, balance_after)
        
        # Calculate max drawdown
        if self.metrics.peak_balance > 0:
            drawdown = (self.metrics.peak_balance - balance_after) / self.metrics.peak_balance
            self.metrics.max_drawdown = max(self.metrics.max_drawdown, drawdown)
        
        # Check for warnings
        self._check_loss_warnings()
        
        logger.info(
            f"Trade recorded | {'WIN' if is_win else 'LOSS'} | "
            f"Profit: {profit:+.2f} | Balance: {balance_after:.2f} | "
            f"Deficit: {self.metrics.deficit:.2f}"
        )
    
    def _check_session_loss_exceeded(self) -> bool:
        """Check if session loss limit exceeded based on strategy"""
        if not self.metrics:
            return False
        
        session_loss = self.metrics.starting_balance - self.metrics.current_balance
        return session_loss >= self.session_loss_limit
    
    def _check_loss_warnings(self):
        """Check and trigger loss limit warnings"""
        if not self.metrics or not self.on_loss_warning:
            return
        
        session_loss = self.metrics.starting_balance - self.metrics.current_balance
        if session_loss <= 0:
            return
        
        loss_percentage = session_loss / self.session_loss_limit
        
        for threshold in self.WARNING_THRESHOLDS:
            if loss_percentage >= threshold and threshold not in self.warnings_sent:
                self.warnings_sent.append(threshold)
                try:
                    self.on_loss_warning(
                        threshold * 100,
                        session_loss,
                        self.session_loss_limit,
                        self.metrics.current_balance
                    )
                except Exception as e:
                    logger.error(f"Loss warning callback error: {e}")
    
    def should_pause_trading(self) -> tuple:
        """
        Check if trading should be paused (recoverable pause, not breach)
        
        Returns:
            tuple: (should_pause: bool, reason: str)
        """
        if not self.metrics:
            return False, ""
        
        # Check if currently in cooldown pause
        if self._pause_triggered:
            elapsed = time.time() - self._pause_start_time
            if elapsed < self._pause_cooldown:
                remaining = int(self._pause_cooldown - elapsed)
                return True, f"Cooldown aktif ({remaining}s tersisa)"
            else:
                # Cooldown expired, auto-resume
                self._auto_resume_from_pause()
                return False, ""
        
        # Too many consecutive losses - trigger pause with cooldown
        if self.metrics.consecutive_losses >= self._consecutive_loss_limit:
            self._trigger_pause(f"{self.metrics.consecutive_losses}x loss berturut-turut")
            return True, self._pause_reason
        
        # Max drawdown exceeded - warning but don't pause
        if self.metrics.max_drawdown > 0.25:
            logger.warning(f"Max drawdown exceeded ({self.metrics.max_drawdown*100:.1f}%)")
        
        # Near session loss limit (90%) - warning
        session_loss = self.metrics.starting_balance - self.metrics.current_balance
        if session_loss >= self.session_loss_limit * 0.90:
            logger.warning("Approaching session loss limit (90%)")
        
        return False, ""
    
    def _trigger_pause(self, reason: str):
        """Trigger a recoverable pause with cooldown"""
        self._pause_triggered = True
        self._pause_reason = reason
        self._pause_start_time = time.time()
        logger.warning(f"Trading paused: {reason} - Cooldown {self._pause_cooldown}s")
        
        if self.on_pause_trading:
            try:
                self.on_pause_trading(reason)
            except Exception as e:
                logger.error(f"Pause callback error: {e}")
    
    def _auto_resume_from_pause(self):
        """Auto-resume trading after cooldown expires"""
        if not self._pause_triggered:
            return
        
        self._pause_triggered = False
        old_reason = self._pause_reason
        self._pause_reason = ""
        self._pause_start_time = 0.0
        
        # Reset consecutive losses counter
        if self.metrics:
            self.metrics.consecutive_losses = 0
        
        # Switch to ANTI_MARTINGALE mode for safer recovery
        if self.recovery_mode == RecoveryMode.FIBONACCI:
            logger.info("Switching to ANTI_MARTINGALE mode for safer recovery")
            self.recovery_mode = RecoveryMode.ANTI_MARTINGALE
        
        logger.info(f"Trading auto-resumed after pause: {old_reason}")
        
        if self.on_resume_trading:
            try:
                self.on_resume_trading()
            except Exception as e:
                logger.error(f"Resume callback error: {e}")
    
    def force_resume(self):
        """Force resume trading from pause state (user initiated)"""
        if self._pause_triggered:
            self._auto_resume_from_pause()
            return True
        return False
    
    def get_pause_status(self) -> Dict[str, Any]:
        """Get current pause status"""
        if not self._pause_triggered:
            return {"paused": False}
        
        elapsed = time.time() - self._pause_start_time
        remaining = max(0, self._pause_cooldown - elapsed)
        
        return {
            "paused": True,
            "reason": self._pause_reason,
            "elapsed": int(elapsed),
            "remaining": int(remaining),
            "cooldown": int(self._pause_cooldown)
        }
    
    def is_paused(self) -> bool:
        """Check if trading is in pause state"""
        if not self._pause_triggered:
            return False
        
        # Check if cooldown expired
        elapsed = time.time() - self._pause_start_time
        if elapsed >= self._pause_cooldown:
            self._auto_resume_from_pause()
            return False
        
        return True
    
    def should_take_profit(self) -> bool:
        """Check if profit target reached"""
        if not self.metrics or self.profit_target <= 0:
            return False
        
        return self.metrics.total_profit >= self.profit_target
    
    def get_next_stake_preview(self, levels: int = 5) -> List[Dict[str, float]]:
        """
        Preview next N stake levels using Fibonacci
        
        Args:
            levels: Number of levels to preview
            
        Returns:
            List of {level, stake, cumulative_loss} dicts
        """
        preview = []
        cumulative = 0
        
        for level in range(min(levels, len(self.FIBONACCI))):
            fib_mult = self.FIBONACCI[level]
            stake = self.base_stake * fib_mult
            cumulative += stake
            
            preview.append({
                "level": level + 1,
                "stake": round(stake, 2),
                "multiplier": fib_mult,
                "cumulative_loss": round(cumulative, 2)
            })
        
        return preview
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get session summary"""
        if not self.metrics:
            return {"status": "no_session"}
        
        win_rate = 0
        if self.metrics.total_trades > 0:
            win_rate = self.metrics.wins / self.metrics.total_trades * 100
        
        session_loss = self.metrics.starting_balance - self.metrics.current_balance
        loss_limit_pct = (session_loss / self.session_loss_limit * 100) if self.session_loss_limit > 0 else 0
        
        should_pause, pause_reason = self.should_pause_trading()
        
        return {
            "starting_balance": self.metrics.starting_balance,
            "current_balance": self.metrics.current_balance,
            "total_profit": self.metrics.total_profit,
            "total_trades": self.metrics.total_trades,
            "wins": self.metrics.wins,
            "losses": self.metrics.losses,
            "win_rate": win_rate,
            "max_drawdown": self.metrics.max_drawdown * 100,
            "max_consecutive_wins": self.metrics.max_consecutive_wins,
            "max_consecutive_losses": self.metrics.max_consecutive_losses,
            "current_deficit": self.metrics.deficit,
            "recovery_level": self.metrics.recovery_level,
            "recovery_mode": self.recovery_mode.value,
            "is_recovering": self.is_recovering,
            "session_loss": session_loss,
            "session_loss_limit": self.session_loss_limit,
            "loss_limit_percentage": loss_limit_pct,
            "should_pause": should_pause,
            "pause_reason": pause_reason
        }
    
    def set_recovery_mode(self, mode: RecoveryMode):
        """Update recovery mode"""
        self.recovery_mode = mode
        logger.info(f"Recovery mode set to: {mode.value}")
    
    def set_risk_level(self, level: RiskLevel):
        """Update risk level"""
        self.risk_level = level
        config = self.RISK_CONFIG[level]
        self.max_levels = config["max_levels"]
        self.max_stake_pct = config["max_stake_pct"]
        logger.info(f"Risk level set to: {level.value}")
    
    def set_base_stake(self, stake: float):
        """Update base stake"""
        self.base_stake = max(0.35, stake)
        logger.info(f"Base stake set to: {self.base_stake:.2f}")
    
    def reset_recovery(self):
        """Reset recovery state"""
        if self.metrics:
            self.metrics.deficit = 0
            self.metrics.recovery_level = 0
        self.is_recovering = False
        logger.info("Recovery state reset")
    
    def _trigger_breach(self, reason: str):
        """Trigger breach state and persist to file"""
        self._breach_triggered = True
        self._breach_reason = reason
        self._save_breach_state()
        logger.error(f"BREACH TRIGGERED: {reason}")
    
    def clear_breach(self):
        """Clear breach state (manual reset only)"""
        self._breach_triggered = False
        self._breach_reason = ""
        self._clear_breach_state()
        logger.info("Breach state cleared")
    
    def is_breached(self) -> tuple:
        """Check if breach state is active"""
        return self._breach_triggered, self._breach_reason
    
    def _save_breach_state(self):
        """Persist breach state to file"""
        try:
            os.makedirs(os.path.dirname(BREACH_STATE_FILE), exist_ok=True)
            state = {
                "triggered": self._breach_triggered,
                "reason": self._breach_reason,
                "timestamp": time.time(),
                "strategy": self.strategy_name,
                "balance_at_breach": self.metrics.current_balance if self.metrics else 0
            }
            with open(BREACH_STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
            logger.info(f"Breach state saved to {BREACH_STATE_FILE}")
        except Exception as e:
            logger.error(f"Failed to save breach state: {e}")
    
    def _load_breach_state(self):
        """Load breach state from file"""
        try:
            if os.path.exists(BREACH_STATE_FILE):
                with open(BREACH_STATE_FILE, 'r') as f:
                    state = json.load(f)
                self._breach_triggered = state.get("triggered", False)
                self._breach_reason = state.get("reason", "")
                if self._breach_triggered:
                    logger.warning(f"Loaded breach state from file: {self._breach_reason}")
        except Exception as e:
            logger.error(f"Failed to load breach state: {e}")
    
    def _clear_breach_state(self):
        """Remove breach state file"""
        try:
            if os.path.exists(BREACH_STATE_FILE):
                os.remove(BREACH_STATE_FILE)
                logger.info("Breach state file removed")
        except Exception as e:
            logger.error(f"Failed to clear breach state file: {e}")
