"""
Circuit Breaker - Rate limiting and fault tolerance for API calls
Implements circuit breaker pattern with exponential backoff
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic, Awaitable
import functools
import asyncio

logger = logging.getLogger(__name__)

T = TypeVar('T')


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitStats:
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0


@dataclass
class RateLimitConfig:
    requests_per_second: float = 10.0
    requests_per_minute: float = 300.0
    burst_size: int = 20
    min_interval_ms: float = 100.0


class RateLimiter:
    """
    Token bucket rate limiter with sliding window
    
    Features:
    - Token bucket algorithm for smooth rate limiting
    - Sliding window for per-minute limits
    - Burst allowance for spikes
    - Thread-safe implementation
    """
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config if config is not None else RateLimitConfig()
        
        self._tokens = self.config.burst_size
        self._last_refill = time.time()
        self._last_request = 0
        
        self._minute_window: deque = deque(maxlen=int(self.config.requests_per_minute))
        
        self._lock = threading.Lock()
        
        self._stats = {
            "total_requests": 0,
            "allowed_requests": 0,
            "throttled_requests": 0,
            "current_rate": 0.0
        }
    
    def acquire(self, timeout: float = 5.0) -> bool:
        """
        Acquire permission to make a request
        
        Args:
            timeout: Maximum time to wait for permission
            
        Returns:
            True if request is allowed, False if timed out
        """
        start_time = time.time()
        
        while True:
            with self._lock:
                self._stats["total_requests"] += 1
                
                self._refill_tokens()
                self._clean_minute_window()
                
                now = time.time()
                time_since_last = (now - self._last_request) * 1000
                
                if time_since_last < self.config.min_interval_ms:
                    wait_time = (self.config.min_interval_ms - time_since_last) / 1000
                    if time.time() - start_time + wait_time > timeout:
                        self._stats["throttled_requests"] += 1
                        return False
                    time.sleep(wait_time)
                    continue
                
                if len(self._minute_window) >= self.config.requests_per_minute:
                    self._stats["throttled_requests"] += 1
                    if time.time() - start_time > timeout:
                        return False
                    time.sleep(0.1)
                    continue
                
                if self._tokens < 1:
                    if time.time() - start_time > timeout:
                        self._stats["throttled_requests"] += 1
                        return False
                    time.sleep(0.1)
                    continue
                
                self._tokens -= 1
                self._last_request = now
                self._minute_window.append(now)
                self._stats["allowed_requests"] += 1
                
                self._update_rate_stats()
                
                return True
    
    def _refill_tokens(self):
        """Refill tokens based on time elapsed"""
        now = time.time()
        elapsed = now - self._last_refill
        
        new_tokens = elapsed * self.config.requests_per_second
        self._tokens = min(self.config.burst_size, self._tokens + new_tokens)
        self._last_refill = now
    
    def _clean_minute_window(self):
        """Remove old entries from minute window"""
        now = time.time()
        cutoff = now - 60
        
        while self._minute_window and self._minute_window[0] < cutoff:
            self._minute_window.popleft()
    
    def _update_rate_stats(self):
        """Update current rate statistics"""
        if len(self._minute_window) >= 2:
            time_span = self._minute_window[-1] - self._minute_window[0]
            if time_span > 0:
                self._stats["current_rate"] = len(self._minute_window) / time_span
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics"""
        with self._lock:
            return {
                **self._stats,
                "tokens_available": self._tokens,
                "minute_window_size": len(self._minute_window)
            }
    
    def reset(self):
        """Reset rate limiter state"""
        with self._lock:
            self._tokens = self.config.burst_size
            self._minute_window.clear()
            self._stats = {
                "total_requests": 0,
                "allowed_requests": 0,
                "throttled_requests": 0,
                "current_rate": 0.0
            }


class CircuitBreaker:
    """
    Circuit Breaker Pattern Implementation
    
    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Failure threshold exceeded, requests are rejected
    - HALF_OPEN: Testing if service recovered, limited requests allowed
    
    Features:
    - Configurable failure threshold
    - Automatic recovery with half-open state
    - Exponential backoff for retries
    - Health monitoring and metrics
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 3,
        timeout: float = 30.0,
        half_open_max_calls: int = 3
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_max_calls = half_open_max_calls
        
        self._state = CircuitState.CLOSED
        self._stats = CircuitStats()
        self._state_changed_at = time.time()
        self._half_open_calls = 0
        
        self._lock = threading.Lock()
        
        self._on_state_change: Optional[Callable[[CircuitState, CircuitState], None]] = None
    
    @property
    def state(self) -> CircuitState:
        """Get current circuit state"""
        with self._lock:
            self._check_state_transition()
            return self._state
    
    def set_state_change_callback(self, callback: Callable[[CircuitState, CircuitState], None]):
        """Set callback for state changes"""
        self._on_state_change = callback
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Execute a function through the circuit breaker
        
        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerError: If circuit is open
            Original exception: If function fails
        """
        with self._lock:
            self._check_state_transition()
            
            if self._state == CircuitState.OPEN:
                self._stats.rejected_calls += 1
                raise CircuitBreakerError(f"Circuit breaker '{self.name}' is OPEN")
            
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerError(f"Circuit breaker '{self.name}' is HALF_OPEN, max calls reached")
                self._half_open_calls += 1
        
        try:
            result = func(*args, **kwargs)
            self._record_success()
            return result
        except Exception as e:
            self._record_failure()
            raise
    
    async def call_async(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Execute an async function through the circuit breaker"""
        with self._lock:
            self._check_state_transition()
            
            if self._state == CircuitState.OPEN:
                self._stats.rejected_calls += 1
                raise CircuitBreakerError(f"Circuit breaker '{self.name}' is OPEN")
            
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerError(f"Circuit breaker '{self.name}' is HALF_OPEN, max calls reached")
                self._half_open_calls += 1
        
        try:
            result = await func(*args, **kwargs)
            self._record_success()
            return result
        except Exception:
            self._record_failure()
            raise
    
    def _record_success(self):
        """Record a successful call"""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.successful_calls += 1
            self._stats.last_success_time = time.time()
            self._stats.consecutive_failures = 0
            self._stats.consecutive_successes += 1
            
            if self._state == CircuitState.HALF_OPEN:
                if self._stats.consecutive_successes >= self.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
    
    def _record_failure(self):
        """Record a failed call"""
        with self._lock:
            self._stats.total_calls += 1
            self._stats.failed_calls += 1
            self._stats.last_failure_time = time.time()
            self._stats.consecutive_successes = 0
            self._stats.consecutive_failures += 1
            
            if self._state == CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
            elif self._state == CircuitState.CLOSED:
                if self._stats.consecutive_failures >= self.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
    
    def _check_state_transition(self):
        """Check if state should transition based on timeout"""
        if self._state == CircuitState.OPEN:
            time_in_open = time.time() - self._state_changed_at
            if time_in_open >= self.timeout:
                self._transition_to(CircuitState.HALF_OPEN)
    
    def _transition_to(self, new_state: CircuitState):
        """Transition to a new state"""
        old_state = self._state
        self._state = new_state
        self._state_changed_at = time.time()
        
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._stats.consecutive_successes = 0
        elif new_state == CircuitState.CLOSED:
            self._stats.consecutive_failures = 0
        
        logger.info(f"Circuit breaker '{self.name}' transitioned: {old_state.value} -> {new_state.value}")
        
        if self._on_state_change:
            try:
                self._on_state_change(old_state, new_state)
            except Exception as e:
                logger.error(f"State change callback error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics"""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "total_calls": self._stats.total_calls,
                "successful_calls": self._stats.successful_calls,
                "failed_calls": self._stats.failed_calls,
                "rejected_calls": self._stats.rejected_calls,
                "consecutive_failures": self._stats.consecutive_failures,
                "consecutive_successes": self._stats.consecutive_successes,
                "last_failure_time": self._stats.last_failure_time,
                "last_success_time": self._stats.last_success_time,
                "state_changed_at": self._state_changed_at,
                "time_in_current_state": time.time() - self._state_changed_at
            }
    
    def reset(self):
        """Reset circuit breaker to closed state"""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._stats = CircuitStats()
            logger.info(f"Circuit breaker '{self.name}' reset")
    
    def force_open(self):
        """Force circuit to open state"""
        with self._lock:
            self._transition_to(CircuitState.OPEN)
            logger.warning(f"Circuit breaker '{self.name}' forced OPEN")


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open"""
    pass


class RetryWithBackoff:
    """
    Retry mechanism with exponential backoff
    
    Features:
    - Configurable retry attempts
    - Exponential backoff with jitter
    - Exception filtering
    - Callback hooks for monitoring
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple = (Exception,)
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
        
        self._on_retry: Optional[Callable[[int, Exception, float], None]] = None
    
    def set_retry_callback(self, callback: Callable[[int, Exception, float], None]):
        """Set callback for retry events: callback(attempt, exception, delay)"""
        self._on_retry = callback
    
    def execute(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute a function with retry logic
        
        Args:
            func: Function to execute
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Function result
            
        Raises:
            Last exception if all retries fail
        """
        last_exception: Optional[Exception] = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except self.retryable_exceptions as e:
                last_exception = e
                
                if attempt == self.max_retries:
                    break
                
                delay = self._calculate_delay(attempt)
                
                logger.warning(
                    f"Retry {attempt + 1}/{self.max_retries} after error: {e}. "
                    f"Waiting {delay:.2f}s"
                )
                
                if self._on_retry:
                    try:
                        self._on_retry(attempt + 1, e, delay)
                    except Exception:
                        pass
                
                time.sleep(delay)
        
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("Retry loop completed without result or exception")
    
    async def execute_async(self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
        """Execute an async function with retry logic"""
        last_exception: Optional[Exception] = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except self.retryable_exceptions as e:
                last_exception = e
                
                if attempt == self.max_retries:
                    break
                
                delay = self._calculate_delay(attempt)
                
                logger.warning(
                    f"Retry {attempt + 1}/{self.max_retries} after error: {e}. "
                    f"Waiting {delay:.2f}s"
                )
                
                if self._on_retry:
                    try:
                        self._on_retry(attempt + 1, e, delay)
                    except Exception:
                        pass
                
                await asyncio.sleep(delay)
        
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("Retry loop completed without result or exception")
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for next retry with exponential backoff"""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            delay = delay * (0.5 + random.random())
        
        return delay


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    timeout: float = 30.0
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to wrap a function with circuit breaker"""
    breaker = CircuitBreaker(name, failure_threshold=failure_threshold, timeout=timeout)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            return breaker.call(func, *args, **kwargs)
        
        setattr(wrapper, 'circuit_breaker', breaker)
        return wrapper
    
    return decorator


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple = (Exception,)
):
    """Decorator to wrap a function with retry logic"""
    retrier = RetryWithBackoff(
        max_retries=max_retries,
        base_delay=base_delay,
        retryable_exceptions=exceptions
    )
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return retrier.execute(func, *args, **kwargs)
        return wrapper
    
    return decorator


class APIClient:
    """
    API Client with built-in rate limiting and circuit breaker
    
    Combines rate limiting, circuit breaker, and retry logic
    for robust API communication
    """
    
    def __init__(
        self,
        name: str,
        rate_limit: Optional[RateLimitConfig] = None,
        circuit_failure_threshold: int = 5,
        circuit_timeout: float = 30.0,
        max_retries: int = 3
    ):
        self.name = name
        
        self.rate_limiter = RateLimiter(rate_limit if rate_limit is not None else RateLimitConfig())
        
        self.circuit_breaker = CircuitBreaker(
            name=f"{name}_circuit",
            failure_threshold=circuit_failure_threshold,
            timeout=circuit_timeout
        )
        
        self.retrier = RetryWithBackoff(
            max_retries=max_retries,
            retryable_exceptions=(Exception,)
        )
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute a function with rate limiting, circuit breaker, and retry"""
        if not self.rate_limiter.acquire(timeout=10.0):
            raise RateLimitError(f"Rate limit exceeded for {self.name}")
        
        def wrapped():
            return self.circuit_breaker.call(func, *args, **kwargs)
        
        return self.retrier.execute(wrapped)
    
    def get_health(self) -> Dict[str, Any]:
        """Get health status of the API client"""
        return {
            "name": self.name,
            "rate_limiter": self.rate_limiter.get_stats(),
            "circuit_breaker": self.circuit_breaker.get_stats()
        }
    
    def reset(self):
        """Reset all components"""
        self.rate_limiter.reset()
        self.circuit_breaker.reset()


class RateLimitError(Exception):
    """Exception raised when rate limit is exceeded"""
    pass


deriv_api_client = APIClient(
    name="deriv_api",
    rate_limit=RateLimitConfig(
        requests_per_second=5.0,
        requests_per_minute=150.0,
        burst_size=10,
        min_interval_ms=200.0
    ),
    circuit_failure_threshold=5,
    circuit_timeout=30.0,
    max_retries=3
)
