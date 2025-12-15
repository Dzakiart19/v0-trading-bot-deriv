"""
Session Awareness - Timezone handling and trading session management
Optimizes trading based on market sessions and liquidity
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MarketSession(Enum):
    ASIAN = "ASIAN"
    EUROPEAN = "EUROPEAN"
    AMERICAN = "AMERICAN"
    PACIFIC = "PACIFIC"
    OFF_HOURS = "OFF_HOURS"


class SessionQuality(Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    MODERATE = "MODERATE"
    POOR = "POOR"
    AVOID = "AVOID"


@dataclass
class SessionInfo:
    session: MarketSession
    quality: SessionQuality
    liquidity_score: float
    volatility_expected: str
    recommended_strategies: List[str]
    avoid_strategies: List[str]
    time_until_next_session: int
    overlap_sessions: List[MarketSession]


class TradingSessionManager:
    """
    Trading Session Management
    
    Features:
    - Market session detection (Asian, European, American, Pacific)
    - Session overlap detection (highest liquidity periods)
    - Session quality scoring
    - Strategy recommendations per session
    - Timezone-aware scheduling
    """
    
    SESSIONS = {
        MarketSession.ASIAN: {
            "start_utc": 0,
            "end_utc": 9,
            "centers": ["Tokyo", "Hong Kong", "Singapore"],
            "volatility": "MODERATE",
            "liquidity": 0.7
        },
        MarketSession.EUROPEAN: {
            "start_utc": 7,
            "end_utc": 16,
            "centers": ["London", "Frankfurt", "Paris"],
            "volatility": "HIGH",
            "liquidity": 0.9
        },
        MarketSession.AMERICAN: {
            "start_utc": 13,
            "end_utc": 22,
            "centers": ["New York", "Chicago"],
            "volatility": "HIGH",
            "liquidity": 0.95
        },
        MarketSession.PACIFIC: {
            "start_utc": 21,
            "end_utc": 6,
            "centers": ["Sydney", "Wellington"],
            "volatility": "LOW",
            "liquidity": 0.5
        }
    }
    
    SESSION_OVERLAPS = {
        ("ASIAN", "EUROPEAN"): {"hours": (7, 9), "quality": SessionQuality.EXCELLENT},
        ("EUROPEAN", "AMERICAN"): {"hours": (13, 16), "quality": SessionQuality.EXCELLENT},
        ("AMERICAN", "PACIFIC"): {"hours": (21, 22), "quality": SessionQuality.GOOD}
    }
    
    STRATEGY_SESSION_PREFERENCES = {
        "SNIPER": {
            "preferred": [MarketSession.EUROPEAN, MarketSession.AMERICAN],
            "avoid": [MarketSession.OFF_HOURS, MarketSession.PACIFIC]
        },
        "TERMINAL": {
            "preferred": [MarketSession.EUROPEAN, MarketSession.AMERICAN],
            "avoid": [MarketSession.OFF_HOURS]
        },
        "MULTI_INDICATOR": {
            "preferred": [MarketSession.EUROPEAN, MarketSession.AMERICAN, MarketSession.ASIAN],
            "avoid": [MarketSession.OFF_HOURS]
        },
        "TICK_PICKER": {
            "preferred": [MarketSession.ASIAN, MarketSession.EUROPEAN],
            "avoid": []
        },
        "DIGITPAD": {
            "preferred": [MarketSession.ASIAN, MarketSession.EUROPEAN],
            "avoid": []
        },
        "LDP": {
            "preferred": [MarketSession.ASIAN, MarketSession.EUROPEAN],
            "avoid": []
        },
        "AMT": {
            "preferred": [MarketSession.EUROPEAN, MarketSession.AMERICAN],
            "avoid": [MarketSession.OFF_HOURS, MarketSession.PACIFIC]
        }
    }
    
    SYNTHETIC_ALWAYS_ACTIVE = [
        "R_10", "R_25", "R_50", "R_75", "R_100",
        "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V"
    ]
    
    def __init__(self, user_timezone: str = "UTC"):
        self.user_timezone = user_timezone
        self._session_cache: Dict[str, SessionInfo] = {}
        self._cache_time = 0
        self._cache_ttl = 300
    
    def get_current_session(self) -> SessionInfo:
        """Get current trading session information"""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        
        cache_key = f"{now.strftime('%Y-%m-%d-%H')}"
        if cache_key in self._session_cache and time.time() - self._cache_time < self._cache_ttl:
            return self._session_cache[cache_key]
        
        active_sessions = []
        for session, config in self.SESSIONS.items():
            start = config["start_utc"]
            end = config["end_utc"]
            
            if start <= end:
                if start <= current_hour < end:
                    active_sessions.append(session)
            else:
                if current_hour >= start or current_hour < end:
                    active_sessions.append(session)
        
        if not active_sessions:
            primary_session = MarketSession.OFF_HOURS
            quality = SessionQuality.AVOID
            liquidity = 0.3
        else:
            primary_session = self._get_primary_session(active_sessions, current_hour)
            quality, liquidity = self._calculate_quality(active_sessions, current_hour)
        
        volatility = "LOW"
        if primary_session != MarketSession.OFF_HOURS:
            volatility = self.SESSIONS[primary_session]["volatility"]
        
        recommended = self._get_recommended_strategies(primary_session, quality)
        avoid = self._get_avoid_strategies(primary_session)
        
        next_session_minutes = self._time_until_next_session(current_hour)
        
        session_info = SessionInfo(
            session=primary_session,
            quality=quality,
            liquidity_score=liquidity,
            volatility_expected=volatility,
            recommended_strategies=recommended,
            avoid_strategies=avoid,
            time_until_next_session=next_session_minutes,
            overlap_sessions=active_sessions if len(active_sessions) > 1 else []
        )
        
        self._session_cache[cache_key] = session_info
        self._cache_time = time.time()
        
        return session_info
    
    def _get_primary_session(self, active_sessions: List[MarketSession], hour: int) -> MarketSession:
        """Determine primary session from active sessions"""
        if len(active_sessions) == 1:
            return active_sessions[0]
        
        best_liquidity = 0
        primary = active_sessions[0]
        
        for session in active_sessions:
            liquidity = self.SESSIONS[session]["liquidity"]
            if liquidity > best_liquidity:
                best_liquidity = liquidity
                primary = session
        
        return primary
    
    def _calculate_quality(self, active_sessions: List[MarketSession], hour: int) -> Tuple[SessionQuality, float]:
        """Calculate session quality and liquidity"""
        if len(active_sessions) >= 2:
            for (s1, s2), config in self.SESSION_OVERLAPS.items():
                sessions_match = (
                    (MarketSession[s1] in active_sessions and MarketSession[s2] in active_sessions)
                )
                if sessions_match:
                    overlap_start, overlap_end = config["hours"]
                    if overlap_start <= hour < overlap_end:
                        return config["quality"], 1.0
            
            return SessionQuality.GOOD, 0.85
        
        if active_sessions:
            session = active_sessions[0]
            liquidity = self.SESSIONS[session]["liquidity"]
            
            if liquidity >= 0.9:
                return SessionQuality.EXCELLENT, liquidity
            elif liquidity >= 0.7:
                return SessionQuality.GOOD, liquidity
            elif liquidity >= 0.5:
                return SessionQuality.MODERATE, liquidity
            else:
                return SessionQuality.POOR, liquidity
        
        return SessionQuality.AVOID, 0.3
    
    def _get_recommended_strategies(self, session: MarketSession, quality: SessionQuality) -> List[str]:
        """Get recommended strategies for current session"""
        recommended = []
        
        for strategy, prefs in self.STRATEGY_SESSION_PREFERENCES.items():
            if session in prefs["preferred"]:
                recommended.append(strategy)
            elif session == MarketSession.OFF_HOURS and session not in prefs.get("avoid", []):
                pass
            elif quality in [SessionQuality.EXCELLENT, SessionQuality.GOOD]:
                if session not in prefs.get("avoid", []):
                    recommended.append(strategy)
        
        return recommended
    
    def _get_avoid_strategies(self, session: MarketSession) -> List[str]:
        """Get strategies to avoid for current session"""
        avoid = []
        
        for strategy, prefs in self.STRATEGY_SESSION_PREFERENCES.items():
            if session in prefs.get("avoid", []):
                avoid.append(strategy)
        
        return avoid
    
    def _time_until_next_session(self, current_hour: int) -> int:
        """Calculate minutes until next major session"""
        next_starts = []
        
        for session, config in self.SESSIONS.items():
            start = config["start_utc"]
            if start > current_hour:
                hours_until = start - current_hour
            else:
                hours_until = (24 - current_hour) + start
            next_starts.append(hours_until * 60)
        
        return min(next_starts) if next_starts else 0
    
    def is_good_time_to_trade(self, strategy: str = None, symbol: str = None) -> Tuple[bool, str]:
        """Check if current time is good for trading"""
        if symbol and symbol in self.SYNTHETIC_ALWAYS_ACTIVE:
            return True, "Synthetic indices are always active"
        
        session_info = self.get_current_session()
        
        if session_info.quality == SessionQuality.AVOID:
            return False, "Off-hours - low liquidity period"
        
        if strategy:
            if strategy in session_info.avoid_strategies:
                return False, f"{strategy} not recommended during {session_info.session.value} session"
            
            if strategy in session_info.recommended_strategies:
                return True, f"Optimal time for {strategy}"
        
        if session_info.quality in [SessionQuality.EXCELLENT, SessionQuality.GOOD]:
            return True, f"Good trading conditions ({session_info.session.value})"
        
        return True, f"Acceptable conditions ({session_info.quality.value})"
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get comprehensive session summary"""
        session_info = self.get_current_session()
        now = datetime.now(timezone.utc)
        
        return {
            "current_time_utc": now.isoformat(),
            "session": session_info.session.value,
            "quality": session_info.quality.value,
            "liquidity_score": session_info.liquidity_score,
            "volatility": session_info.volatility_expected,
            "recommended_strategies": session_info.recommended_strategies,
            "avoid_strategies": session_info.avoid_strategies,
            "is_overlap": len(session_info.overlap_sessions) > 1,
            "overlap_sessions": [s.value for s in session_info.overlap_sessions],
            "minutes_until_next": session_info.time_until_next_session
        }
    
    def get_best_trading_windows(self, hours_ahead: int = 24) -> List[Dict[str, Any]]:
        """Get best trading windows in the next N hours"""
        windows = []
        now = datetime.now(timezone.utc)
        
        for hour_offset in range(hours_ahead):
            check_time = now + timedelta(hours=hour_offset)
            hour = check_time.hour
            
            active = []
            for session, config in self.SESSIONS.items():
                start = config["start_utc"]
                end = config["end_utc"]
                
                if start <= end:
                    if start <= hour < end:
                        active.append(session)
                else:
                    if hour >= start or hour < end:
                        active.append(session)
            
            if len(active) >= 2:
                quality, liquidity = self._calculate_quality(active, hour)
                if quality in [SessionQuality.EXCELLENT, SessionQuality.GOOD]:
                    windows.append({
                        "time_utc": check_time.isoformat(),
                        "hour_offset": hour_offset,
                        "sessions": [s.value for s in active],
                        "quality": quality.value,
                        "liquidity": liquidity
                    })
        
        return windows[:10]


session_manager = TradingSessionManager()


def is_good_trading_time(strategy: str = None, symbol: str = None) -> Tuple[bool, str]:
    """Convenience function to check trading time"""
    return session_manager.is_good_time_to_trade(strategy, symbol)


def get_session_info() -> Dict[str, Any]:
    """Get current session information"""
    return session_manager.get_session_summary()
