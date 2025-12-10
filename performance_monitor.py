"""
Performance Monitor - Metrics tracking and alerting
"""

import logging
import os
import time
import threading
import json
from collections import deque
from dataclasses import dataclass, asdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics snapshot"""
    timestamp: float
    tick_processing_time_avg: float  # ms
    tick_processing_time_max: float  # ms
    websocket_latency: float  # ms
    trade_execution_time_avg: float  # ms
    memory_usage_mb: float
    active_connections: int
    trades_per_minute: float
    error_rate: float
    is_healthy: bool


class PerformanceMonitor:
    """
    Performance Monitor
    
    Features:
    - Tick processing time tracking
    - WebSocket latency monitoring
    - Trade execution time measurement
    - Memory usage tracking
    - Error rate calculation
    - Alerting via Telegram when performance degrades
    """
    
    # Thresholds for alerts
    MAX_TICK_PROCESSING_MS = 100  # Alert if > 100ms
    MAX_WEBSOCKET_LATENCY_MS = 500  # Alert if > 500ms
    MAX_TRADE_EXECUTION_MS = 5000  # Alert if > 5s
    MAX_ERROR_RATE = 0.10  # Alert if > 10% error rate
    MAX_MEMORY_MB = 500  # Alert if > 500MB
    
    def __init__(self):
        # Metric histories
        self.tick_times: deque = deque(maxlen=100)
        self.ws_latencies: deque = deque(maxlen=50)
        self.trade_times: deque = deque(maxlen=50)
        self.error_counts: deque = deque(maxlen=100)
        
        # Counters
        self.total_ticks = 0
        self.total_trades = 0
        self.total_errors = 0
        self.start_time = time.time()
        
        # Session metrics
        self._session_start = time.time()
        self._trade_timestamps: deque = deque(maxlen=100)
        
        # Alerting
        self.on_alert: Optional[Callable] = None
        self._last_alert_time = 0
        self._alert_cooldown = 300  # 5 minutes between alerts
        
        # Monitoring thread
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._monitor_interval = 60  # Check every 60 seconds
        
        # Metrics history for /metrics endpoint
        self._metrics_history: deque = deque(maxlen=100)
    
    def start(self):
        """Start performance monitoring"""
        self._running = True
        self._session_start = time.time()
        
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        
        logger.info("Performance monitor started")
    
    def stop(self):
        """Stop performance monitoring"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Performance monitor stopped")
    
    def record_tick_processing(self, duration_ms: float):
        """Record tick processing time"""
        self.tick_times.append(duration_ms)
        self.total_ticks += 1
    
    def record_websocket_latency(self, latency_ms: float):
        """Record WebSocket latency"""
        self.ws_latencies.append(latency_ms)
    
    def record_trade_execution(self, duration_ms: float):
        """Record trade execution time"""
        self.trade_times.append(duration_ms)
        self.total_trades += 1
        self._trade_timestamps.append(time.time())
    
    def record_error(self, error_type: str = "general"):
        """Record an error"""
        self.error_counts.append({
            "type": error_type,
            "timestamp": time.time()
        })
        self.total_errors += 1
    
    def get_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics"""
        # Calculate averages
        tick_avg = sum(self.tick_times) / len(self.tick_times) if self.tick_times else 0
        tick_max = max(self.tick_times) if self.tick_times else 0
        ws_latency = sum(self.ws_latencies) / len(self.ws_latencies) if self.ws_latencies else 0
        trade_avg = sum(self.trade_times) / len(self.trade_times) if self.trade_times else 0
        
        # Memory usage
        memory_mb = self._get_memory_usage()
        
        # Trades per minute
        trades_per_min = self._calculate_trades_per_minute()
        
        # Error rate (last 100 operations)
        recent_errors = sum(1 for e in self.error_counts if time.time() - e["timestamp"] < 300)
        total_recent = self.total_ticks + self.total_trades
        error_rate = recent_errors / max(1, total_recent % 1000)
        
        # Health check
        is_healthy = self._check_health(tick_avg, ws_latency, trade_avg, error_rate, memory_mb)
        
        return PerformanceMetrics(
            timestamp=time.time(),
            tick_processing_time_avg=round(tick_avg, 2),
            tick_processing_time_max=round(tick_max, 2),
            websocket_latency=round(ws_latency, 2),
            trade_execution_time_avg=round(trade_avg, 2),
            memory_usage_mb=round(memory_mb, 2),
            active_connections=1,  # Placeholder
            trades_per_minute=round(trades_per_min, 2),
            error_rate=round(error_rate, 4),
            is_healthy=is_healthy
        )
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            import psutil
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            # Fallback if psutil not available
            try:
                with open('/proc/self/statm', 'r') as f:
                    pages = int(f.read().split()[1])
                    return pages * 4096 / 1024 / 1024
            except:
                return 0
    
    def _calculate_trades_per_minute(self) -> float:
        """Calculate trades per minute"""
        now = time.time()
        recent_trades = [t for t in self._trade_timestamps if now - t < 60]
        return len(recent_trades)
    
    def _check_health(
        self, 
        tick_avg: float, 
        ws_latency: float, 
        trade_avg: float,
        error_rate: float,
        memory_mb: float
    ) -> bool:
        """Check if performance is healthy"""
        issues = []
        
        if tick_avg > self.MAX_TICK_PROCESSING_MS:
            issues.append(f"High tick processing: {tick_avg:.0f}ms")
        
        if ws_latency > self.MAX_WEBSOCKET_LATENCY_MS:
            issues.append(f"High WS latency: {ws_latency:.0f}ms")
        
        if trade_avg > self.MAX_TRADE_EXECUTION_MS:
            issues.append(f"Slow trade execution: {trade_avg:.0f}ms")
        
        if error_rate > self.MAX_ERROR_RATE:
            issues.append(f"High error rate: {error_rate*100:.1f}%")
        
        if memory_mb > self.MAX_MEMORY_MB:
            issues.append(f"High memory: {memory_mb:.0f}MB")
        
        if issues:
            self._maybe_send_alert(issues)
            return False
        
        return True
    
    def _maybe_send_alert(self, issues: List[str]):
        """Send alert if cooldown has passed"""
        now = time.time()
        if now - self._last_alert_time < self._alert_cooldown:
            return
        
        self._last_alert_time = now
        
        message = "⚠️ Performance Alert:\n" + "\n".join(f"• {issue}" for issue in issues)
        
        if self.on_alert:
            try:
                self.on_alert(message)
            except Exception as e:
                logger.error(f"Failed to send performance alert: {e}")
        
        logger.warning(f"Performance issues: {issues}")
    
    def _monitor_loop(self):
        """Background monitoring loop"""
        while self._running:
            try:
                time.sleep(self._monitor_interval)
                
                metrics = self.get_metrics()
                self._metrics_history.append(asdict(metrics))
                
                if not metrics.is_healthy:
                    logger.warning(f"Performance degraded: {asdict(metrics)}")
                
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
    
    def get_metrics_json(self) -> Dict[str, Any]:
        """Get metrics as JSON-serializable dict"""
        current = self.get_metrics()
        
        return {
            "current": asdict(current),
            "uptime_seconds": time.time() - self.start_time,
            "total_ticks": self.total_ticks,
            "total_trades": self.total_trades,
            "total_errors": self.total_errors,
            "history": list(self._metrics_history)[-10:]  # Last 10 snapshots
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get performance summary"""
        metrics = self.get_metrics()
        uptime = time.time() - self.start_time
        
        return {
            "status": "healthy" if metrics.is_healthy else "degraded",
            "uptime_minutes": round(uptime / 60, 1),
            "tick_processing_ms": metrics.tick_processing_time_avg,
            "websocket_latency_ms": metrics.websocket_latency,
            "trade_execution_ms": metrics.trade_execution_time_avg,
            "memory_mb": metrics.memory_usage_mb,
            "trades_per_minute": metrics.trades_per_minute,
            "error_rate_percent": metrics.error_rate * 100,
            "total_ticks": self.total_ticks,
            "total_trades": self.total_trades
        }


# Global instance
performance_monitor = PerformanceMonitor()
