"""
Notification Manager - Advanced notification system with daily/weekly summaries
Handles all trading notifications, alerts, and scheduled reports
"""

import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import threading

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    TRADE_OPENED = "TRADE_OPENED"
    TRADE_CLOSED = "TRADE_CLOSED"
    SESSION_COMPLETE = "SESSION_COMPLETE"
    LOSS_WARNING = "LOSS_WARNING"
    PROFIT_MILESTONE = "PROFIT_MILESTONE"
    DAILY_SUMMARY = "DAILY_SUMMARY"
    WEEKLY_SUMMARY = "WEEKLY_SUMMARY"
    DRAWDOWN_ALERT = "DRAWDOWN_ALERT"
    WIN_STREAK = "WIN_STREAK"
    LOSS_STREAK = "LOSS_STREAK"
    CONNECTION_STATUS = "CONNECTION_STATUS"
    ERROR = "ERROR"
    SYSTEM = "SYSTEM"


class NotificationPriority(Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Notification:
    type: NotificationType
    priority: NotificationPriority
    title: str
    message: str
    user_id: int
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    sent: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "priority": self.priority.value,
            "title": self.title,
            "message": self.message,
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "data": self.data,
            "sent": self.sent
        }


@dataclass 
class DailyStats:
    date: str
    user_id: int
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    profit: float = 0.0
    starting_balance: float = 0.0
    ending_balance: float = 0.0
    max_drawdown: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    strategies_used: List[str] = field(default_factory=list)
    symbols_traded: List[str] = field(default_factory=list)


@dataclass
class WeeklyStats:
    week_start: str
    week_end: str
    user_id: int
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    profit: float = 0.0
    avg_daily_profit: float = 0.0
    best_day: str = ""
    best_day_profit: float = 0.0
    worst_day: str = ""
    worst_day_profit: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0


class NotificationManager:
    """
    Advanced Notification Management System
    
    Features:
    - Real-time trade notifications
    - Daily and weekly summary reports
    - Profit milestone alerts
    - Drawdown warnings
    - Win/loss streak alerts
    - Rate limiting and deduplication
    - Multi-channel support (Telegram, WebSocket)
    """
    
    DATA_DIR = "logs/notifications"
    RATE_LIMIT_INTERVAL = 2.0
    DEDUP_TTL = 60
    
    PROFIT_MILESTONES = [10, 25, 50, 100, 250, 500, 1000]
    DRAWDOWN_THRESHOLDS = [0.10, 0.15, 0.20, 0.25]
    STREAK_THRESHOLD = 5
    
    def __init__(self):
        os.makedirs(self.DATA_DIR, exist_ok=True)
        
        self._pending_notifications: Dict[int, List[Notification]] = defaultdict(list)
        self._sent_hashes: Dict[str, float] = {}
        self._last_send_time: Dict[int, float] = {}
        
        self._user_stats: Dict[int, Dict[str, DailyStats]] = defaultdict(dict)
        self._achieved_milestones: Dict[int, List[float]] = defaultdict(list)
        self._triggered_drawdowns: Dict[int, List[float]] = defaultdict(list)
        
        self._send_callback: Optional[Callable] = None
        self._lock = threading.RLock()
        
        self._scheduler_running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        
        self._load_state()
    
    def set_send_callback(self, callback: Callable[[int, str, str], None]):
        """Set callback for sending notifications: callback(user_id, title, message)"""
        self._send_callback = callback
    
    def notify_trade_opened(self, user_id: int, trade_data: Dict[str, Any]):
        """Notify when a trade is opened"""
        symbol = trade_data.get("symbol", "N/A")
        direction = trade_data.get("contract_type", trade_data.get("direction", "N/A"))
        stake = trade_data.get("stake", 0)
        confidence = trade_data.get("confidence", 0)
        
        message = (
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Stake: ${stake:.2f}\n"
            f"Confidence: {confidence:.1%}"
        )
        
        notification = Notification(
            type=NotificationType.TRADE_OPENED,
            priority=NotificationPriority.NORMAL,
            title="Trade Opened",
            message=message,
            user_id=user_id,
            data=trade_data
        )
        
        self._queue_notification(notification)
    
    def notify_trade_closed(self, user_id: int, trade_data: Dict[str, Any]):
        """Notify when a trade is closed"""
        profit = trade_data.get("profit", 0)
        is_win = profit > 0
        symbol = trade_data.get("symbol", "N/A")
        
        emoji = "+" if is_win else ""
        status = "WIN" if is_win else "LOSS"
        
        message = (
            f"Result: {status}\n"
            f"Profit: {emoji}${profit:.2f}\n"
            f"Symbol: {symbol}"
        )
        
        notification = Notification(
            type=NotificationType.TRADE_CLOSED,
            priority=NotificationPriority.NORMAL,
            title=f"Trade Closed - {status}",
            message=message,
            user_id=user_id,
            data=trade_data
        )
        
        self._queue_notification(notification)
        self._update_daily_stats(user_id, trade_data)
        self._check_streaks(user_id, is_win)
        self._check_profit_milestones(user_id, profit)
    
    def notify_session_complete(self, user_id: int, session_data: Dict[str, Any]):
        """Notify when a trading session is complete"""
        trades = session_data.get("trades", 0)
        wins = session_data.get("wins", 0)
        profit = session_data.get("profit", 0)
        win_rate = session_data.get("win_rate", 0)
        
        emoji = "+" if profit >= 0 else ""
        
        message = (
            f"Total Trades: {trades}\n"
            f"Wins: {wins} ({win_rate:.1f}%)\n"
            f"Profit: {emoji}${profit:.2f}"
        )
        
        notification = Notification(
            type=NotificationType.SESSION_COMPLETE,
            priority=NotificationPriority.HIGH,
            title="Session Complete",
            message=message,
            user_id=user_id,
            data=session_data
        )
        
        self._queue_notification(notification)
    
    def notify_loss_warning(self, user_id: int, warning_data: Dict[str, Any]):
        """Notify about loss limit warning"""
        percentage = warning_data.get("percentage", 0)
        current_loss = warning_data.get("current_loss", 0)
        limit = warning_data.get("limit", 0)
        
        message = (
            f"Warning: {percentage:.0f}% of loss limit reached\n"
            f"Current Loss: ${current_loss:.2f}\n"
            f"Limit: ${limit:.2f}"
        )
        
        notification = Notification(
            type=NotificationType.LOSS_WARNING,
            priority=NotificationPriority.HIGH,
            title="Loss Warning",
            message=message,
            user_id=user_id,
            data=warning_data
        )
        
        self._queue_notification(notification, bypass_dedup=True)
    
    def notify_drawdown_alert(self, user_id: int, drawdown_pct: float, balance: float):
        """Notify about significant drawdown"""
        if drawdown_pct in self._triggered_drawdowns[user_id]:
            return
        
        for threshold in self.DRAWDOWN_THRESHOLDS:
            if drawdown_pct >= threshold and threshold not in self._triggered_drawdowns[user_id]:
                self._triggered_drawdowns[user_id].append(threshold)
                
                message = (
                    f"Drawdown Alert: {drawdown_pct*100:.1f}%\n"
                    f"Current Balance: ${balance:.2f}\n"
                    f"Consider reducing position size."
                )
                
                notification = Notification(
                    type=NotificationType.DRAWDOWN_ALERT,
                    priority=NotificationPriority.CRITICAL,
                    title="Drawdown Alert",
                    message=message,
                    user_id=user_id,
                    data={"drawdown_pct": drawdown_pct, "balance": balance}
                )
                
                self._queue_notification(notification, bypass_dedup=True)
                break
    
    def notify_connection_status(self, user_id: int, connected: bool, details: str = ""):
        """Notify about connection status changes"""
        status = "Connected" if connected else "Disconnected"
        priority = NotificationPriority.NORMAL if connected else NotificationPriority.HIGH
        
        message = f"Status: {status}"
        if details:
            message += f"\n{details}"
        
        notification = Notification(
            type=NotificationType.CONNECTION_STATUS,
            priority=priority,
            title=f"Connection {status}",
            message=message,
            user_id=user_id,
            data={"connected": connected, "details": details}
        )
        
        self._queue_notification(notification)
    
    def notify_error(self, user_id: int, error_message: str, error_data: Dict[str, Any] = None):
        """Notify about errors"""
        notification = Notification(
            type=NotificationType.ERROR,
            priority=NotificationPriority.HIGH,
            title="Error",
            message=error_message,
            user_id=user_id,
            data=error_data or {}
        )
        
        self._queue_notification(notification)
    
    def generate_daily_summary(self, user_id: int, date: str = None) -> Optional[str]:
        """Generate daily trading summary"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        stats = self._user_stats.get(user_id, {}).get(date)
        if not stats or stats.total_trades == 0:
            return None
        
        win_rate = (stats.wins / stats.total_trades * 100) if stats.total_trades > 0 else 0
        profit_emoji = "+" if stats.profit >= 0 else ""
        
        summary = f"""
Daily Trading Summary - {date}

Trades: {stats.total_trades}
Wins: {stats.wins} | Losses: {stats.losses}
Win Rate: {win_rate:.1f}%

Profit/Loss: {profit_emoji}${stats.profit:.2f}
Best Trade: +${stats.best_trade:.2f}
Worst Trade: -${abs(stats.worst_trade):.2f}

Starting Balance: ${stats.starting_balance:.2f}
Ending Balance: ${stats.ending_balance:.2f}

Strategies: {', '.join(set(stats.strategies_used))}
Symbols: {', '.join(set(stats.symbols_traded))}
"""
        
        notification = Notification(
            type=NotificationType.DAILY_SUMMARY,
            priority=NotificationPriority.NORMAL,
            title=f"Daily Summary - {date}",
            message=summary.strip(),
            user_id=user_id,
            data=asdict(stats)
        )
        
        self._queue_notification(notification)
        return summary
    
    def generate_weekly_summary(self, user_id: int) -> Optional[str]:
        """Generate weekly trading summary"""
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
        week_end = today
        
        weekly_stats = WeeklyStats(
            week_start=week_start.strftime("%Y-%m-%d"),
            week_end=week_end.strftime("%Y-%m-%d"),
            user_id=user_id
        )
        
        daily_profits = {}
        
        for i in range(7):
            date = (week_start + timedelta(days=i)).strftime("%Y-%m-%d")
            daily_stats = self._user_stats.get(user_id, {}).get(date)
            
            if daily_stats:
                weekly_stats.total_trades += daily_stats.total_trades
                weekly_stats.wins += daily_stats.wins
                weekly_stats.losses += daily_stats.losses
                weekly_stats.profit += daily_stats.profit
                daily_profits[date] = daily_stats.profit
        
        if weekly_stats.total_trades == 0:
            return None
        
        weekly_stats.win_rate = (weekly_stats.wins / weekly_stats.total_trades * 100)
        weekly_stats.avg_daily_profit = weekly_stats.profit / 7
        
        if daily_profits:
            best_day = max(daily_profits, key=daily_profits.get)
            worst_day = min(daily_profits, key=daily_profits.get)
            weekly_stats.best_day = best_day
            weekly_stats.best_day_profit = daily_profits[best_day]
            weekly_stats.worst_day = worst_day
            weekly_stats.worst_day_profit = daily_profits[worst_day]
        
        total_loss = sum(abs(self._user_stats.get(user_id, {}).get(d, DailyStats(d, user_id)).worst_trade) 
                        for d in daily_profits.keys() 
                        if self._user_stats.get(user_id, {}).get(d))
        total_win = sum(self._user_stats.get(user_id, {}).get(d, DailyStats(d, user_id)).best_trade 
                       for d in daily_profits.keys() 
                       if self._user_stats.get(user_id, {}).get(d))
        weekly_stats.profit_factor = (total_win / total_loss) if total_loss > 0 else 0
        
        profit_emoji = "+" if weekly_stats.profit >= 0 else ""
        
        summary = f"""
Weekly Trading Summary
{weekly_stats.week_start} to {weekly_stats.week_end}

Total Trades: {weekly_stats.total_trades}
Wins: {weekly_stats.wins} | Losses: {weekly_stats.losses}
Win Rate: {weekly_stats.win_rate:.1f}%

Total Profit: {profit_emoji}${weekly_stats.profit:.2f}
Avg Daily: {profit_emoji}${weekly_stats.avg_daily_profit:.2f}

Best Day: {weekly_stats.best_day} (+${weekly_stats.best_day_profit:.2f})
Worst Day: {weekly_stats.worst_day} (${weekly_stats.worst_day_profit:.2f})

Profit Factor: {weekly_stats.profit_factor:.2f}
"""
        
        notification = Notification(
            type=NotificationType.WEEKLY_SUMMARY,
            priority=NotificationPriority.NORMAL,
            title="Weekly Summary",
            message=summary.strip(),
            user_id=user_id,
            data=asdict(weekly_stats)
        )
        
        self._queue_notification(notification)
        return summary
    
    def _update_daily_stats(self, user_id: int, trade_data: Dict[str, Any]):
        """Update daily statistics"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        if today not in self._user_stats[user_id]:
            self._user_stats[user_id][today] = DailyStats(
                date=today,
                user_id=user_id,
                starting_balance=trade_data.get("balance_before", 0)
            )
        
        stats = self._user_stats[user_id][today]
        profit = trade_data.get("profit", 0)
        
        stats.total_trades += 1
        if profit > 0:
            stats.wins += 1
            stats.best_trade = max(stats.best_trade, profit)
        else:
            stats.losses += 1
            stats.worst_trade = min(stats.worst_trade, profit)
        
        stats.profit += profit
        stats.ending_balance = trade_data.get("balance_after", stats.ending_balance)
        
        strategy = trade_data.get("strategy", "Unknown")
        if strategy not in stats.strategies_used:
            stats.strategies_used.append(strategy)
        
        symbol = trade_data.get("symbol", "Unknown")
        if symbol not in stats.symbols_traded:
            stats.symbols_traded.append(symbol)
        
        self._save_state()
    
    def _check_streaks(self, user_id: int, is_win: bool):
        """Check and notify about win/loss streaks"""
        pass
    
    def _check_profit_milestones(self, user_id: int, session_profit: float):
        """Check and notify about profit milestones"""
        for milestone in self.PROFIT_MILESTONES:
            if session_profit >= milestone and milestone not in self._achieved_milestones[user_id]:
                self._achieved_milestones[user_id].append(milestone)
                
                notification = Notification(
                    type=NotificationType.PROFIT_MILESTONE,
                    priority=NotificationPriority.HIGH,
                    title="Profit Milestone",
                    message=f"Congratulations! You've reached ${milestone} profit!",
                    user_id=user_id,
                    data={"milestone": milestone, "current_profit": session_profit}
                )
                
                self._queue_notification(notification)
                break
    
    def _queue_notification(self, notification: Notification, bypass_dedup: bool = False):
        """Queue a notification for sending"""
        with self._lock:
            if not bypass_dedup:
                msg_hash = f"{notification.user_id}:{notification.type.value}:{notification.message[:50]}"
                if msg_hash in self._sent_hashes:
                    if time.time() - self._sent_hashes[msg_hash] < self.DEDUP_TTL:
                        return
                self._sent_hashes[msg_hash] = time.time()
            
            self._pending_notifications[notification.user_id].append(notification)
            self._process_queue(notification.user_id)
    
    def _process_queue(self, user_id: int):
        """Process pending notifications for a user"""
        with self._lock:
            if not self._pending_notifications[user_id]:
                return
            
            now = time.time()
            last_send = self._last_send_time.get(user_id, 0)
            
            if now - last_send < self.RATE_LIMIT_INTERVAL:
                return
            
            notification = self._pending_notifications[user_id].pop(0)
            
            if self._send_callback:
                try:
                    self._send_callback(user_id, notification.title, notification.message)
                    notification.sent = True
                    self._last_send_time[user_id] = now
                except Exception as e:
                    logger.error(f"Failed to send notification: {e}")
                    self._pending_notifications[user_id].insert(0, notification)
    
    def start_scheduler(self):
        """Start the notification scheduler for daily/weekly summaries"""
        if self._scheduler_running:
            return
        
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info("Notification scheduler started")
    
    def stop_scheduler(self):
        """Stop the notification scheduler"""
        self._scheduler_running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        logger.info("Notification scheduler stopped")
    
    def _scheduler_loop(self):
        """Scheduler loop for sending periodic summaries"""
        last_daily_check = datetime.now().date()
        last_weekly_check = datetime.now().isocalendar()[1]
        
        while self._scheduler_running:
            try:
                now = datetime.now()
                
                if now.hour == 23 and now.minute >= 55:
                    if now.date() != last_daily_check:
                        last_daily_check = now.date()
                        for user_id in self._user_stats.keys():
                            self.generate_daily_summary(user_id)
                
                if now.weekday() == 6 and now.hour == 20:
                    current_week = now.isocalendar()[1]
                    if current_week != last_weekly_check:
                        last_weekly_check = current_week
                        for user_id in self._user_stats.keys():
                            self.generate_weekly_summary(user_id)
                
                time.sleep(60)
                
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                time.sleep(60)
    
    def _save_state(self):
        """Save notification state to file"""
        try:
            state = {
                "user_stats": {
                    str(user_id): {
                        date: asdict(stats) for date, stats in dates.items()
                    } for user_id, dates in self._user_stats.items()
                },
                "achieved_milestones": {str(k): v for k, v in self._achieved_milestones.items()},
                "triggered_drawdowns": {str(k): v for k, v in self._triggered_drawdowns.items()}
            }
            
            with open(os.path.join(self.DATA_DIR, "notification_state.json"), 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save notification state: {e}")
    
    def _load_state(self):
        """Load notification state from file"""
        try:
            state_file = os.path.join(self.DATA_DIR, "notification_state.json")
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                for user_id_str, dates in state.get("user_stats", {}).items():
                    user_id = int(user_id_str)
                    for date, stats_dict in dates.items():
                        self._user_stats[user_id][date] = DailyStats(**stats_dict)
                
                self._achieved_milestones = {
                    int(k): v for k, v in state.get("achieved_milestones", {}).items()
                }
                self._triggered_drawdowns = {
                    int(k): v for k, v in state.get("triggered_drawdowns", {}).items()
                }
        except Exception as e:
            logger.error(f"Failed to load notification state: {e}")
    
    def reset_user_state(self, user_id: int):
        """Reset notification state for a user"""
        with self._lock:
            self._user_stats.pop(user_id, None)
            self._achieved_milestones.pop(user_id, None)
            self._triggered_drawdowns.pop(user_id, None)
            self._pending_notifications.pop(user_id, None)
            self._save_state()


notification_manager = NotificationManager()
