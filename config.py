"""
Configuration - Central configuration management
"""

import os
import json
import logging
import secrets
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level options"""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class BotConfig:
    """
    Main bot configuration
    """
    # Telegram
    telegram_token: str = ""
    
    # Deriv API
    deriv_app_id: str = "1089"  # Default app ID
    deriv_endpoint: str = "wss://ws.binaryws.com/websockets/v3"
    
    # Web Server
    web_host: str = "0.0.0.0"
    web_port: int = 5000
    flask_secret: str = ""  # Must be set via FLASK_SECRET_KEY env var
    admin_username: str = ""  # Must be set via ADMIN_USERNAME env var
    admin_password: str = ""  # Must be set via ADMIN_PASSWORD env var
    
    # Trading Defaults
    default_stake: float = 1.0
    default_target_trades: int = 50
    default_duration: int = 5
    default_duration_unit: str = "t"
    default_risk_level: str = "MEDIUM"
    
    # Martingale
    use_martingale: bool = True
    max_martingale_level: int = 5
    martingale_multiplier: float = 2.2
    
    # Risk Management
    daily_loss_limit: float = 50.0
    max_consecutive_losses: int = 7
    stop_on_loss_limit: bool = True
    
    # Strategy Defaults
    default_strategy: str = "MULTI_INDICATOR"
    
    # Logging
    log_level: str = "INFO"
    log_to_file: bool = True
    log_file: str = "logs/trading.log"
    
    @classmethod
    def from_env(cls) -> "BotConfig":
        """Load configuration from environment variables"""
        return cls(
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            deriv_app_id=os.environ.get("DERIV_APP_ID", "") or "1089",
            deriv_endpoint=os.environ.get("DERIV_ENDPOINT", "wss://ws.binaryws.com/websockets/v3"),
            web_host=os.environ.get("WEB_HOST", "0.0.0.0"),
            web_port=int(os.environ.get("WEB_PORT", "5000")),
            flask_secret=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
            admin_username=os.environ.get("ADMIN_USERNAME") or "",  # Disabled if not set
            admin_password=os.environ.get("ADMIN_PASSWORD") or "",  # Disabled if not set
            default_stake=float(os.environ.get("DEFAULT_STAKE", "1.0")),
            default_target_trades=int(os.environ.get("DEFAULT_TARGET_TRADES", "50")),
            default_risk_level=os.environ.get("DEFAULT_RISK_LEVEL", "MEDIUM"),
            daily_loss_limit=float(os.environ.get("DAILY_LOSS_LIMIT", "50.0")),
            max_martingale_level=int(os.environ.get("MAX_MARTINGALE_LEVEL", "5")),
            log_level=os.environ.get("LOG_LEVEL", "INFO")
        )
    
    @classmethod
    def from_file(cls, path: str) -> "BotConfig":
        """Load configuration from JSON file"""
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return cls(**data)
        except FileNotFoundError:
            logger.warning(f"Config file not found: {path}, using defaults")
            return cls()
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return cls()
    
    def save(self, path: str):
        """Save configuration to JSON file"""
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


@dataclass
class UserConfig:
    """
    Per-user configuration
    """
    user_id: int
    language: str = "id"
    
    # Trading preferences
    preferred_symbol: str = "R_100"
    preferred_strategy: str = "MULTI_INDICATOR"
    preferred_duration: int = 5
    preferred_duration_unit: str = "t"
    
    # Stake settings
    base_stake: float = 1.0
    use_martingale: bool = True
    martingale_multiplier: float = 2.2
    max_martingale_level: int = 5
    
    # Session settings
    target_trades: int = 50
    daily_loss_limit: float = 50.0
    daily_profit_target: float = 100.0
    
    # Notifications
    notify_all_trades: bool = True
    notify_wins_only: bool = False
    notify_session_summary: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserConfig":
        """Create from dictionary"""
        return cls(**data)


class ConfigManager:
    """
    Configuration manager with persistence
    """
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self._bot_config: Optional[BotConfig] = None
        self._user_configs: Dict[int, UserConfig] = {}
        
        os.makedirs(config_dir, exist_ok=True)
    
    def get_bot_config(self) -> BotConfig:
        """Get bot configuration"""
        if not self._bot_config:
            config_path = os.path.join(self.config_dir, "bot_config.json")
            if os.path.exists(config_path):
                self._bot_config = BotConfig.from_file(config_path)
            else:
                self._bot_config = BotConfig.from_env()
        return self._bot_config
    
    def save_bot_config(self, config: BotConfig):
        """Save bot configuration"""
        self._bot_config = config
        config_path = os.path.join(self.config_dir, "bot_config.json")
        config.save(config_path)
    
    def get_user_config(self, user_id: int) -> UserConfig:
        """Get user configuration"""
        if user_id not in self._user_configs:
            config_path = os.path.join(self.config_dir, f"user_{user_id}.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        data = json.load(f)
                    self._user_configs[user_id] = UserConfig.from_dict(data)
                except Exception as e:
                    logger.error(f"Error loading user config: {e}")
                    self._user_configs[user_id] = UserConfig(user_id=user_id)
            else:
                self._user_configs[user_id] = UserConfig(user_id=user_id)
        
        return self._user_configs[user_id]
    
    def save_user_config(self, config: UserConfig):
        """Save user configuration"""
        self._user_configs[config.user_id] = config
        config_path = os.path.join(self.config_dir, f"user_{config.user_id}.json")
        
        with open(config_path, "w") as f:
            json.dump(config.to_dict(), f, indent=2)
    
    def update_user_config(self, user_id: int, **kwargs):
        """Update specific user config fields"""
        config = self.get_user_config(user_id)
        
        for key, value in kwargs.items():
            if hasattr(config, key):
                setattr(config, key, value)
        
        self.save_user_config(config)
        return config


# Global config manager
config_manager = ConfigManager()
