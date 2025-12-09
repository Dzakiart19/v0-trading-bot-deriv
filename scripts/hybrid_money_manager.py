"""
Hybrid Money Manager - Progressive recovery system with risk management
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"

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
    Hybrid Money Manager with Progressive Recovery
    
    Features:
    - Progressive recovery system (safer than pure Martingale)
    - Deficit tracking for gradual recovery
    - Risk-based multipliers and max levels
    - Capital protection limits
    - Daily loss limit enforcement
    """
    
    # Risk configurations
    RISK_CONFIG = {
        RiskLevel.LOW: {"multiplier": 1.5, "max_levels": 6},
        RiskLevel.MEDIUM: {"multiplier": 1.8, "max_levels": 5},
        RiskLevel.HIGH: {"multiplier": 2.1, "max_levels": 4},
        RiskLevel.VERY_HIGH: {"multiplier": 2.5, "max_levels": 3}
    }
    
    def __init__(
        self,
        base_stake: float = 1.0,
        risk_level: RiskLevel = RiskLevel.MEDIUM,
        daily_loss_limit: float = 50.0,
        profit_target: float = 0.0  # 0 = no target
    ):
        self.base_stake = base_stake
        self.risk_level = risk_level
        self.daily_loss_limit = daily_loss_limit
        self.profit_target = profit_target
        
        # Get risk config
        config = self.RISK_CONFIG[risk_level]
        self.multiplier = config["multiplier"]
        self.max_levels = config["max_levels"]
        
        # Session state
        self.metrics: Optional[SessionMetrics] = None
        self.trade_history: deque = deque(maxlen=200)
        self.is_recovering = False
    
    def start_session(self, starting_balance: float):
        """Initialize a new trading session"""
        self.metrics = SessionMetrics(
            starting_balance=starting_balance,
            current_balance=starting_balance,
            peak_balance=starting_balance,
            lowest_balance=starting_balance
        )
        self.trade_history.clear()
        self.is_recovering = False
        
        logger.info(
            f"Session started | Balance: {starting_balance:.2f} | "
            f"Risk: {self.risk_level.value} | Base stake: {self.base_stake:.2f}"
        )
    
    def calculate_stake(self) -> float:
        """
        Calculate next stake amount
        
        Returns:
            Recommended stake amount
        """
        if not self.metrics:
            return self.base_stake
        
        balance = self.metrics.current_balance
        
        # Check if we should stop (daily loss limit)
        if self._check_daily_loss_exceeded():
            logger.warning("Daily loss limit reached - stopping")
            return 0
        
        # Base case: no deficit, return base stake
        if self.metrics.deficit <= 0:
            self.is_recovering = False
            return min(self.base_stake, balance * 0.05)  # Max 5% of balance
        
        # Recovery mode
        self.is_recovering = True
        level = self.metrics.recovery_level
        
        if level >= self.max_levels:
            logger.warning(f"Max recovery level ({self.max_levels}) reached")
            # Reset and use base stake
            self.metrics.deficit = 0
            self.metrics.recovery_level = 0
            self.is_recovering = False
            return min(self.base_stake, balance * 0.05)
        
        # Progressive recovery calculation
        # Level 1: base * multiplier
        # Level 2: base * multiplier^1.5
        # Level 3: base * multiplier^2
        exponent = 1 + (level * 0.5)
        stake = self.base_stake * (self.multiplier ** exponent)
        
        # Capital protection: max 20% of balance
        max_stake = balance * 0.20
        stake = min(stake, max_stake)
        
        # Minimum stake
        stake = max(stake, 0.35)
        
        logger.debug(
            f"Recovery stake: {stake:.2f} | Level: {level + 1}/{self.max_levels} | "
            f"Deficit: {self.metrics.deficit:.2f}"
        )
        
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
            timestamp=0  # Would be time.time() in production
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
                # Reduce deficit by profit
                self.metrics.deficit = max(0, self.metrics.deficit - profit)
                
                if self.metrics.deficit <= 0:
                    logger.info("Recovery complete!")
                    self.metrics.recovery_level = 0
                    self.is_recovering = False
                else:
                    # Reset level but keep deficit
                    self.metrics.recovery_level = 0
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
        
        logger.info(
            f"Trade recorded | {'WIN' if is_win else 'LOSS'} | "
            f"Profit: {profit:+.2f} | Balance: {balance_after:.2f} | "
            f"Deficit: {self.metrics.deficit:.2f}"
        )
    
    def should_take_profit(self) -> bool:
        """Check if profit target reached"""
        if not self.metrics or self.profit_target <= 0:
            return False
        
        return self.metrics.total_profit >= self.profit_target
    
    def _check_daily_loss_exceeded(self) -> bool:
        """Check if daily loss limit exceeded"""
        if not self.metrics:
            return False
        
        session_loss = self.metrics.starting_balance - self.metrics.current_balance
        return session_loss >= self.daily_loss_limit
    
    def get_next_stake_preview(self, levels: int = 5) -> List[Dict[str, float]]:
        """
        Preview next N stake levels
        
        Args:
            levels: Number of levels to preview
            
        Returns:
            List of {level, stake, cumulative_loss} dicts
        """
        preview = []
        cumulative = 0
        
        for level in range(levels):
            exponent = 1 + (level * 0.5)
            stake = self.base_stake * (self.multiplier ** exponent)
            cumulative += stake
            
            preview.append({
                "level": level + 1,
                "stake": round(stake, 2),
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
            "is_recovering": self.is_recovering
        }
    
    def set_risk_level(self, level: RiskLevel):
        """Update risk level"""
        self.risk_level = level
        config = self.RISK_CONFIG[level]
        self.multiplier = config["multiplier"]
        self.max_levels = config["max_levels"]
        logger.info(f"Risk level set to: {level.value}")
    
    def set_base_stake(self, stake: float):
        """Update base stake"""
        self.base_stake = max(0.35, stake)
        logger.info(f"Base stake set to: {self.base_stake:.2f}")
