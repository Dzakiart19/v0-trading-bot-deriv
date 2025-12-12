"""
User Preferences Storage - Persistent user settings
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class UserPreferences:
    """User trading preferences"""
    user_id: int
    
    # Trading preferences
    preferred_strategy: str = "TERMINAL"
    preferred_symbol: str = "R_100"
    preferred_stake: float = 1.0
    
    # Session settings
    target_trades: int = 50
    take_profit: float = 10.0
    stop_loss: float = 25.0
    
    # Risk settings
    risk_level: str = "MEDIUM"
    use_martingale: bool = False
    recovery_mode: str = "FIBONACCI"
    
    # Notification settings
    notify_all_trades: bool = True
    notify_wins_only: bool = False
    notify_session_summary: bool = True
    notify_performance_alerts: bool = True
    
    # Duration settings
    preferred_duration: int = 5
    preferred_duration_unit: str = "t"
    
    # Language
    language: str = "id"
    
    # Last session info
    last_login_time: float = 0
    last_balance: float = 0
    total_profit: float = 0
    total_trades: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserPreferences":
        """Create from dictionary"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


class UserPreferencesManager:
    """
    Manager for user preferences with file-based persistence
    
    Features:
    - Auto-save on changes
    - Load on demand
    - Restore last session settings
    - Track performance history
    """
    
    STORAGE_DIR = "config/users"
    
    def __init__(self):
        self._cache: Dict[int, UserPreferences] = {}
        os.makedirs(self.STORAGE_DIR, exist_ok=True)
    
    def _get_file_path(self, user_id: int) -> str:
        """Get file path for user preferences"""
        return os.path.join(self.STORAGE_DIR, f"user_{user_id}.json")
    
    def get(self, user_id: int) -> UserPreferences:
        """Get user preferences, creating default if not exists"""
        # Check cache first
        if user_id in self._cache:
            return self._cache[user_id]
        
        # Try to load from file
        file_path = self._get_file_path(user_id)
        
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                prefs = UserPreferences.from_dict(data)
                self._cache[user_id] = prefs
                return prefs
            except Exception as e:
                logger.error(f"Error loading preferences for user {user_id}: {e}")
        
        # Create default preferences
        prefs = UserPreferences(user_id=user_id)
        self._cache[user_id] = prefs
        self.save(prefs)
        
        return prefs
    
    def save(self, prefs: UserPreferences):
        """Save user preferences to file"""
        try:
            file_path = self._get_file_path(prefs.user_id)
            with open(file_path, 'w') as f:
                json.dump(prefs.to_dict(), f, indent=2)
            self._cache[prefs.user_id] = prefs
            logger.debug(f"Saved preferences for user {prefs.user_id}")
        except Exception as e:
            logger.error(f"Error saving preferences for user {prefs.user_id}: {e}")
    
    def update(self, user_id: int, **kwargs) -> UserPreferences:
        """Update specific fields for a user"""
        prefs = self.get(user_id)
        
        for key, value in kwargs.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        
        self.save(prefs)
        return prefs
    
    def update_after_login(self, user_id: int, balance: float):
        """Update preferences after successful login"""
        import time
        self.update(
            user_id,
            last_login_time=time.time(),
            last_balance=balance
        )
    
    def update_after_trade(self, user_id: int, profit: float, is_win: bool):
        """Update preferences after a trade"""
        prefs = self.get(user_id)
        prefs.total_profit += profit
        prefs.total_trades += 1
        self.save(prefs)
    
    def get_last_session_config(self, user_id: int) -> Dict[str, Any]:
        """Get last session configuration for restore"""
        prefs = self.get(user_id)
        
        return {
            "strategy": prefs.preferred_strategy,
            "symbol": prefs.preferred_symbol,
            "stake": prefs.preferred_stake,
            "target_trades": prefs.target_trades,
            "take_profit": prefs.take_profit,
            "stop_loss": prefs.stop_loss,
            "risk_level": prefs.risk_level,
            "use_martingale": prefs.use_martingale,
            "recovery_mode": prefs.recovery_mode,
            "duration": prefs.preferred_duration,
            "duration_unit": prefs.preferred_duration_unit
        }
    
    def save_session_config(
        self, 
        user_id: int, 
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        stake: Optional[float] = None,
        **kwargs: Any
    ) -> None:
        """Save current session config as preferences"""
        updates = {}
        
        if strategy:
            updates["preferred_strategy"] = strategy
        if symbol:
            updates["preferred_symbol"] = symbol
        if stake:
            updates["preferred_stake"] = stake
        
        # Add any other kwargs that match preference fields
        prefs = self.get(user_id)
        for key, value in kwargs.items():
            if hasattr(prefs, key) and value is not None:
                updates[key] = value
        
        if updates:
            self.update(user_id, **updates)
    
    def get_stats(self, user_id: int) -> Dict[str, Any]:
        """Get user stats summary"""
        prefs = self.get(user_id)
        
        return {
            "total_trades": prefs.total_trades,
            "total_profit": prefs.total_profit,
            "last_balance": prefs.last_balance,
            "preferred_strategy": prefs.preferred_strategy,
            "preferred_symbol": prefs.preferred_symbol,
            "last_login": prefs.last_login_time
        }
    
    def delete(self, user_id: int):
        """Delete user preferences"""
        try:
            file_path = self._get_file_path(user_id)
            if os.path.exists(file_path):
                os.remove(file_path)
            if user_id in self._cache:
                del self._cache[user_id]
            logger.info(f"Deleted preferences for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting preferences for user {user_id}: {e}")
    
    def list_users(self) -> list:
        """List all users with stored preferences"""
        users = []
        try:
            for filename in os.listdir(self.STORAGE_DIR):
                if filename.startswith("user_") and filename.endswith(".json"):
                    user_id = int(filename[5:-5])
                    users.append(user_id)
        except Exception as e:
            logger.error(f"Error listing users: {e}")
        return users


# Global instance
user_preferences = UserPreferencesManager()
