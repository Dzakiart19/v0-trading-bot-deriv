"""
Logging Utilities - Throttled logging to reduce log flooding
"""

import logging
import time
from collections import defaultdict
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ThrottledLogger:
    """
    A logger wrapper that throttles repeated log messages.
    Useful for high-frequency events like tick updates, heartbeats, etc.
    """
    
    def __init__(self, base_logger: logging.Logger, min_interval: float = 5.0):
        self._logger = base_logger
        self._min_interval = min_interval
        self._last_log_times: Dict[str, float] = defaultdict(float)
        self._suppressed_counts: Dict[str, int] = defaultdict(int)
    
    def _should_log(self, key: str) -> bool:
        now = time.time()
        if now - self._last_log_times[key] >= self._min_interval:
            self._last_log_times[key] = now
            return True
        self._suppressed_counts[key] += 1
        return False
    
    def _get_suppressed_suffix(self, key: str) -> str:
        count = self._suppressed_counts.get(key, 0)
        if count > 0:
            self._suppressed_counts[key] = 0
            return f" (+{count} suppressed)"
        return ""
    
    def debug(self, msg: str, key: Optional[str] = None, *args, **kwargs):
        log_key = key or msg[:50]
        if self._should_log(log_key):
            suffix = self._get_suppressed_suffix(log_key)
            self._logger.debug(f"{msg}{suffix}", *args, **kwargs)
    
    def info(self, msg: str, key: Optional[str] = None, *args, **kwargs):
        log_key = key or msg[:50]
        if self._should_log(log_key):
            suffix = self._get_suppressed_suffix(log_key)
            self._logger.info(f"{msg}{suffix}", *args, **kwargs)
    
    def warning(self, msg: str, key: Optional[str] = None, *args, **kwargs):
        log_key = key or msg[:50]
        if self._should_log(log_key):
            suffix = self._get_suppressed_suffix(log_key)
            self._logger.warning(f"{msg}{suffix}", *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        self._logger.error(msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        self._logger.critical(msg, *args, **kwargs)
    
    def force_log(self, level: int, msg: str, *args, **kwargs):
        self._logger.log(level, msg, *args, **kwargs)


class LogRateLimiter:
    """
    Simple rate limiter for specific log messages.
    Allows N messages per time window.
    """
    
    def __init__(self, max_per_window: int = 10, window_seconds: float = 60.0):
        self._max_per_window = max_per_window
        self._window_seconds = window_seconds
        self._message_counts: Dict[str, list] = defaultdict(list)
    
    def should_log(self, key: str) -> bool:
        now = time.time()
        timestamps = self._message_counts[key]
        
        timestamps[:] = [t for t in timestamps if now - t < self._window_seconds]
        
        if len(timestamps) < self._max_per_window:
            timestamps.append(now)
            return True
        return False
    
    def get_suppressed_count(self, key: str) -> int:
        now = time.time()
        return sum(1 for t in self._message_counts[key] if now - t >= self._window_seconds)


def create_throttled_logger(name: str, interval: float = 5.0) -> ThrottledLogger:
    """Create a throttled logger for a module"""
    base_logger = logging.getLogger(name)
    return ThrottledLogger(base_logger, interval)


def configure_log_levels():
    """Configure appropriate log levels for different modules"""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websocket").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
