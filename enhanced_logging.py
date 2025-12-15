"""
Enhanced Logging System - Structured logging with rotation and centralized management
"""

import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from typing import Any, Dict, List, Optional
import threading

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        if hasattr(record, 'extra_data'):
            log_data["data"] = record.extra_data
        
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored console formatter"""
    
    COLORS = {
        'DEBUG': '\033[36m',
        'INFO': '\033[32m',
        'WARNING': '\033[33m',
        'ERROR': '\033[31m',
        'CRITICAL': '\033[35m'
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


class LogBuffer:
    """In-memory log buffer for real-time viewing"""
    
    def __init__(self, max_size: int = 1000):
        self._buffer: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()
    
    def add(self, record: Dict[str, Any]):
        with self._lock:
            self._buffer.append(record)
    
    def get_recent(self, count: int = 100, level: str = None) -> List[Dict[str, Any]]:
        with self._lock:
            logs = list(self._buffer)
            if level:
                logs = [l for l in logs if l.get("level") == level]
            return logs[-count:]
    
    def clear(self):
        with self._lock:
            self._buffer.clear()


class BufferedHandler(logging.Handler):
    """Handler that stores logs in buffer"""
    
    def __init__(self, buffer: LogBuffer):
        super().__init__()
        self.buffer = buffer
    
    def emit(self, record: logging.LogRecord):
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module
        }
        self.buffer.add(log_data)


class ThrottledHandler(logging.Handler):
    """Handler that throttles repeated messages"""
    
    def __init__(self, base_handler: logging.Handler, interval: float = 1.0):
        super().__init__()
        self.base_handler = base_handler
        self.interval = interval
        self._last_messages: Dict[str, float] = {}
        self._suppressed_counts: Dict[str, int] = {}
        self._lock = threading.Lock()
    
    def emit(self, record: logging.LogRecord):
        msg_key = f"{record.name}:{record.levelno}:{record.getMessage()[:100]}"
        now = time.time()
        
        with self._lock:
            last_time = self._last_messages.get(msg_key, 0)
            
            if now - last_time < self.interval:
                self._suppressed_counts[msg_key] = self._suppressed_counts.get(msg_key, 0) + 1
                return
            
            suppressed = self._suppressed_counts.pop(msg_key, 0)
            if suppressed > 0:
                record.msg = f"{record.msg} (repeated {suppressed}x)"
            
            self._last_messages[msg_key] = now
        
        self.base_handler.emit(record)


log_buffer = LogBuffer()


def setup_logging(
    level: str = "INFO",
    log_file: str = None,
    structured: bool = False,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    throttle_interval: float = 1.0
):
    """
    Setup enhanced logging configuration
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Path to log file (optional)
        structured: Use JSON structured logging
        max_bytes: Max log file size before rotation
        backup_count: Number of backup files to keep
        throttle_interval: Minimum interval between repeated messages
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    if structured:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))
    
    throttled_console = ThrottledHandler(console_handler, throttle_interval)
    root_logger.addHandler(throttled_console)
    
    if log_file:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)
    
    buffer_handler = BufferedHandler(log_buffer)
    buffer_handler.setLevel(logging.INFO)
    root_logger.addHandler(buffer_handler)
    
    noisy_loggers = [
        "websocket", "urllib3", "httpcore", "httpx",
        "telegram.ext", "asyncio"
    ]
    for logger_name in noisy_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_recent_logs(count: int = 100, level: str = None) -> List[Dict[str, Any]]:
    """Get recent logs from buffer"""
    return log_buffer.get_recent(count, level)


def get_error_logs(count: int = 50) -> List[Dict[str, Any]]:
    """Get recent error logs"""
    return log_buffer.get_recent(count, "ERROR")


class LogContext:
    """Context manager for adding extra data to logs"""
    
    def __init__(self, **extra_data):
        self.extra_data = extra_data
        self._old_factory = None
    
    def __enter__(self):
        self._old_factory = logging.getLogRecordFactory()
        extra = self.extra_data
        
        def factory(*args, **kwargs):
            record = self._old_factory(*args, **kwargs)
            record.extra_data = extra
            return record
        
        logging.setLogRecordFactory(factory)
        return self
    
    def __exit__(self, *args):
        logging.setLogRecordFactory(self._old_factory)


def log_with_context(logger: logging.Logger, level: int, message: str, **context):
    """Log a message with additional context data"""
    with LogContext(**context):
        logger.log(level, message)
