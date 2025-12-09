"""
Event Bus - Async PubSub system for real-time event broadcasting
"""

import asyncio
import logging
import threading
from typing import Dict, Any, Optional, Callable, List, Set
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)

class EventChannel(Enum):
    TICK = "tick"
    POSITION = "position"
    TRADE = "trade"
    BALANCE = "balance"
    STATUS = "status"
    SIGNAL = "signal"

@dataclass
class TickEvent:
    """Price tick event"""
    symbol: str
    quote: float
    epoch: int
    pip_size: int = 2

@dataclass
class PositionOpenEvent:
    """Position opened event"""
    contract_id: str
    symbol: str
    direction: str
    stake: float
    payout: float
    entry_price: float

@dataclass
class PositionUpdateEvent:
    """Position update event"""
    contract_id: str
    current_price: float
    profit: float
    status: str

@dataclass
class PositionCloseEvent:
    """Position closed event"""
    contract_id: str
    exit_price: float
    profit: float
    result: str  # WIN or LOSS

@dataclass
class PositionsResetEvent:
    """All positions cleared event"""
    reason: str = "session_end"

@dataclass
class BalanceUpdateEvent:
    """Balance update event"""
    balance: float
    currency: str

@dataclass
class TradeHistoryEvent:
    """Trade history entry event"""
    trade_id: str
    symbol: str
    direction: str
    stake: float
    profit: float
    result: str
    timestamp: float

@dataclass
class StatusEvent:
    """Bot status event"""
    state: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SignalEvent:
    """Strategy signal event"""
    symbol: str
    direction: str
    confidence: float
    confluence: float
    reason: str
    indicators: Dict[str, Any] = field(default_factory=dict)

class EventBus:
    """
    Async Event Bus for real-time event broadcasting
    
    Features:
    - Thread-safe publishing from sync code
    - Multiple channels for different event types
    - In-memory snapshots for new subscribers
    - Automatic subscriber cleanup
    """
    
    MAX_QUEUE_SIZE = 1000
    MAX_TRADE_HISTORY = 200
    
    def __init__(self):
        self._subscribers: Dict[EventChannel, Set[asyncio.Queue]] = {
            channel: set() for channel in EventChannel
        }
        self._lock = threading.RLock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        # Snapshots for new subscribers
        self._last_tick: Dict[str, TickEvent] = {}
        self._last_balance: Optional[BalanceUpdateEvent] = None
        self._last_status: Optional[StatusEvent] = None
        self._trade_history: deque = deque(maxlen=self.MAX_TRADE_HISTORY)
        self._active_positions: Dict[str, PositionOpenEvent] = {}
    
    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the event loop for async operations"""
        self._loop = loop
    
    def publish(self, channel: EventChannel, event: Any):
        """Publish event to channel (thread-safe)"""
        with self._lock:
            # Update snapshots
            self._update_snapshot(channel, event)
            
            # Get subscribers for channel
            subscribers = self._subscribers.get(channel, set())
            dead_subscribers = set()
            
            for queue in subscribers:
                try:
                    if self._loop and self._loop.is_running():
                        self._loop.call_soon_threadsafe(
                            self._safe_put, queue, event
                        )
                    else:
                        # Sync fallback
                        if not queue.full():
                            queue.put_nowait(event)
                except Exception as e:
                    logger.debug(f"Failed to publish to subscriber: {e}")
                    dead_subscribers.add(queue)
            
            # Cleanup dead subscribers
            for dead in dead_subscribers:
                subscribers.discard(dead)
    
    def _safe_put(self, queue: asyncio.Queue, event: Any):
        """Safely put event in queue"""
        try:
            if not queue.full():
                queue.put_nowait(event)
        except Exception as e:
            logger.debug(f"Error putting event in queue: {e}")
    
    def _update_snapshot(self, channel: EventChannel, event: Any):
        """Update in-memory snapshots"""
        if channel == EventChannel.TICK and isinstance(event, TickEvent):
            self._last_tick[event.symbol] = event
        
        elif channel == EventChannel.BALANCE and isinstance(event, BalanceUpdateEvent):
            self._last_balance = event
        
        elif channel == EventChannel.STATUS and isinstance(event, StatusEvent):
            self._last_status = event
        
        elif channel == EventChannel.TRADE and isinstance(event, TradeHistoryEvent):
            self._trade_history.append(event)
        
        elif channel == EventChannel.POSITION:
            if isinstance(event, PositionOpenEvent):
                self._active_positions[event.contract_id] = event
            elif isinstance(event, PositionCloseEvent):
                self._active_positions.pop(event.contract_id, None)
            elif isinstance(event, PositionsResetEvent):
                self._active_positions.clear()
    
    async def subscribe(self, channel: EventChannel) -> asyncio.Queue:
        """Subscribe to a channel and return queue for events"""
        queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        
        with self._lock:
            self._subscribers[channel].add(queue)
        
        return queue
    
    def unsubscribe(self, channel: EventChannel, queue: asyncio.Queue):
        """Unsubscribe from a channel"""
        with self._lock:
            self._subscribers[channel].discard(queue)
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current state snapshot for new subscribers"""
        with self._lock:
            return {
                "ticks": {s: vars(e) for s, e in self._last_tick.items()},
                "balance": vars(self._last_balance) if self._last_balance else None,
                "status": vars(self._last_status) if self._last_status else None,
                "positions": {k: vars(v) for k, v in self._active_positions.items()},
                "trade_history": [vars(t) for t in self._trade_history]
            }
    
    def get_trade_history(self) -> List[Dict[str, Any]]:
        """Get trade history"""
        with self._lock:
            return [vars(t) for t in self._trade_history]
    
    def cleanup_dead_subscribers(self):
        """Remove dead subscriber queues"""
        with self._lock:
            for channel in EventChannel:
                dead = set()
                for queue in self._subscribers[channel]:
                    try:
                        # Check if queue is still valid
                        _ = queue.qsize()
                    except Exception:
                        dead.add(queue)
                
                for d in dead:
                    self._subscribers[channel].discard(d)

# Global event bus instance
event_bus = EventBus()
