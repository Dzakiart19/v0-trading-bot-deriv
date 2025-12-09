"""
Session Manager - Manages trading sessions and state
"""

import json
import logging
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session states"""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass
class TradeRecord:
    """Individual trade record"""
    trade_id: str
    symbol: str
    direction: str
    stake: float
    payout: float
    entry_price: float
    exit_price: float
    profit: float
    result: str  # WIN, LOSS
    strategy: str
    martingale_level: int
    duration: int
    duration_unit: str
    timestamp: float
    contract_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradingSession:
    """Trading session data"""
    session_id: str
    user_id: int
    symbol: str
    strategy: str
    
    # State
    state: SessionState = SessionState.IDLE
    
    # Configuration
    base_stake: float = 1.0
    target_trades: int = 50
    duration: int = 5
    duration_unit: str = "t"
    use_martingale: bool = True
    max_martingale_level: int = 5
    daily_loss_limit: float = 50.0
    
    # Statistics
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_profit: float = 0.0
    starting_balance: float = 0.0
    current_balance: float = 0.0
    peak_balance: float = 0.0
    max_drawdown: float = 0.0
    
    # Streak tracking
    current_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    consecutive_losses: int = 0
    
    # Martingale state
    current_martingale_level: int = 0
    martingale_stake: float = 0.0
    
    # Timing
    start_time: float = 0.0
    end_time: float = 0.0
    last_trade_time: float = 0.0
    
    # Trade history
    trades: List[TradeRecord] = field(default_factory=list)
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.wins / self.total_trades) * 100
    
    @property
    def duration_seconds(self) -> float:
        if self.state == SessionState.RUNNING:
            return time.time() - self.start_time
        return self.end_time - self.start_time
    
    @property
    def is_target_reached(self) -> bool:
        return self.total_trades >= self.target_trades
    
    @property
    def is_loss_limit_reached(self) -> bool:
        return self.total_profit <= -self.daily_loss_limit
    
    def record_trade(self, trade: TradeRecord):
        """Record a completed trade"""
        self.trades.append(trade)
        self.total_trades += 1
        self.total_profit += trade.profit
        self.current_balance += trade.profit
        self.last_trade_time = trade.timestamp
        
        if trade.result == "WIN":
            self.wins += 1
            self.consecutive_losses = 0
            self.current_streak = max(1, self.current_streak + 1) if self.current_streak >= 0 else 1
            self.max_win_streak = max(self.max_win_streak, self.current_streak)
            
            # Reset martingale on win
            self.current_martingale_level = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
            self.current_streak = min(-1, self.current_streak - 1) if self.current_streak <= 0 else -1
            self.max_loss_streak = max(self.max_loss_streak, abs(self.current_streak))
            
            # Increase martingale level
            if self.use_martingale:
                self.current_martingale_level = min(
                    self.current_martingale_level + 1,
                    self.max_martingale_level
                )
        
        # Update peak and drawdown
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        drawdown = self.peak_balance - self.current_balance
        self.max_drawdown = max(self.max_drawdown, drawdown)
    
    def start(self, balance: float):
        """Start the session"""
        self.state = SessionState.RUNNING
        self.starting_balance = balance
        self.current_balance = balance
        self.peak_balance = balance
        self.start_time = time.time()
    
    def stop(self, reason: str = "user"):
        """Stop the session"""
        self.state = SessionState.STOPPED
        self.end_time = time.time()
        logger.info(f"Session {self.session_id} stopped: {reason}")
    
    def complete(self):
        """Mark session as completed"""
        self.state = SessionState.COMPLETED
        self.end_time = time.time()
    
    def pause(self):
        """Pause the session"""
        self.state = SessionState.PAUSED
    
    def resume(self):
        """Resume the session"""
        self.state = SessionState.RUNNING
    
    def get_summary(self) -> Dict[str, Any]:
        """Get session summary"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "state": self.state.value,
            "total_trades": self.total_trades,
            "target_trades": self.target_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": self.win_rate,
            "total_profit": self.total_profit,
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            "max_drawdown": self.max_drawdown,
            "max_win_streak": self.max_win_streak,
            "max_loss_streak": self.max_loss_streak,
            "duration_seconds": self.duration_seconds
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        data["state"] = self.state.value
        data["trades"] = [t.to_dict() if isinstance(t, TradeRecord) else t for t in self.trades]
        return data


class SessionManager:
    """
    Manages all trading sessions
    """
    
    def __init__(self):
        self._sessions: Dict[str, TradingSession] = {}
        self._user_sessions: Dict[int, str] = {}  # user_id -> active session_id
        self._session_counter = 0
    
    def create_session(
        self,
        user_id: int,
        symbol: str,
        strategy: str,
        **kwargs
    ) -> TradingSession:
        """Create a new trading session"""
        self._session_counter += 1
        session_id = f"session_{user_id}_{self._session_counter}_{int(time.time())}"
        
        session = TradingSession(
            session_id=session_id,
            user_id=user_id,
            symbol=symbol,
            strategy=strategy,
            **kwargs
        )
        
        self._sessions[session_id] = session
        self._user_sessions[user_id] = session_id
        
        logger.info(f"Created session {session_id} for user {user_id}")
        return session
    
    def get_session(self, session_id: str) -> Optional[TradingSession]:
        """Get session by ID"""
        return self._sessions.get(session_id)
    
    def get_user_session(self, user_id: int) -> Optional[TradingSession]:
        """Get active session for user"""
        session_id = self._user_sessions.get(user_id)
        if session_id:
            return self._sessions.get(session_id)
        return None
    
    def get_active_sessions(self) -> List[TradingSession]:
        """Get all active sessions"""
        return [
            s for s in self._sessions.values()
            if s.state == SessionState.RUNNING
        ]
    
    def end_session(self, session_id: str, reason: str = "completed"):
        """End a session"""
        session = self._sessions.get(session_id)
        if session:
            if reason == "completed":
                session.complete()
            else:
                session.stop(reason)
            
            # Remove from active user sessions
            if self._user_sessions.get(session.user_id) == session_id:
                del self._user_sessions[session.user_id]
    
    def get_user_history(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Get session history for user"""
        user_sessions = [
            s for s in self._sessions.values()
            if s.user_id == user_id and s.state in [SessionState.COMPLETED, SessionState.STOPPED]
        ]
        
        # Sort by end time, most recent first
        user_sessions.sort(key=lambda s: s.end_time, reverse=True)
        
        return [s.get_summary() for s in user_sessions[:limit]]
    
    def get_daily_stats(self, user_id: int) -> Dict[str, Any]:
        """Get daily statistics for user"""
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_timestamp = today_start.timestamp()
        
        today_sessions = [
            s for s in self._sessions.values()
            if s.user_id == user_id and s.start_time >= today_timestamp
        ]
        
        total_trades = sum(s.total_trades for s in today_sessions)
        total_wins = sum(s.wins for s in today_sessions)
        total_profit = sum(s.total_profit for s in today_sessions)
        
        return {
            "sessions": len(today_sessions),
            "total_trades": total_trades,
            "wins": total_wins,
            "losses": total_trades - total_wins,
            "win_rate": (total_wins / total_trades * 100) if total_trades > 0 else 0,
            "total_profit": total_profit
        }


# Global session manager
session_manager = SessionManager()
