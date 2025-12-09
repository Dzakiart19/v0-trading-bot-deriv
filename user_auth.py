"""
User Authentication - Per-user encrypted token storage with session management
"""

import os
import json
import time
import hashlib
import logging
import secrets
import threading
from typing import Dict, Optional, Any
from dataclasses import dataclass, asdict
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

logger = logging.getLogger(__name__)

@dataclass
class UserSession:
    """User session data"""
    user_id: int
    token_encrypted: str
    token_fingerprint: str  # SHA-256 hash for audit
    account_type: str  # "demo" or "real"
    language: str
    login_time: float
    last_activity: float

class UserAuth:
    """
    User Authentication System
    
    Features:
    - Per-user encrypted token storage
    - Fernet encryption (AES-128-CBC)
    - PBKDF2 key derivation
    - Rate limiting for login attempts
    - Session persistence
    """
    
    AUTH_FILE = "logs/user_auth.json"
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = 300  # 5 minutes
    PENDING_TIMEOUT = 300  # 5 minutes
    KDF_ITERATIONS = 100000
    
    def __init__(self):
        self._sessions: Dict[int, UserSession] = {}
        self._pending_logins: Dict[int, Dict] = {}  # user_id -> {account_type, timestamp}
        self._login_attempts: Dict[int, Dict] = {}  # user_id -> {count, lockout_until}
        self._lock = threading.RLock()
        
        # Initialize encryption
        self._secret = self._get_or_create_secret()
        self._fernet = self._create_fernet()
        
        # Load existing sessions
        self._load_sessions()
    
    def _get_or_create_secret(self) -> str:
        """Get or create session secret"""
        secret = os.environ.get("SESSION_SECRET")
        
        if not secret:
            secret_file = "logs/.session_secret"
            if os.path.exists(secret_file):
                with open(secret_file, 'r') as f:
                    secret = f.read().strip()
            else:
                secret = secrets.token_hex(32)
                os.makedirs("logs", exist_ok=True)
                with open(secret_file, 'w') as f:
                    f.write(secret)
                logger.info("Generated new session secret")
        
        return secret
    
    def _create_fernet(self) -> Fernet:
        """Create Fernet cipher with derived key"""
        salt = b"deriv_bot_salt_v1"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.KDF_ITERATIONS
        )
        key = base64.urlsafe_b64encode(kdf.derive(self._secret.encode()))
        return Fernet(key)
    
    def _load_sessions(self):
        """Load sessions from file"""
        if not os.path.exists(self.AUTH_FILE):
            return
        
        try:
            with open(self.AUTH_FILE, 'r') as f:
                data = json.load(f)
            
            for user_id_str, session_data in data.get("sessions", {}).items():
                user_id = int(user_id_str)
                self._sessions[user_id] = UserSession(**session_data)
            
            logger.info(f"Loaded {len(self._sessions)} user sessions")
        except Exception as e:
            logger.error(f"Error loading sessions: {e}")
    
    def _save_sessions(self):
        """Save sessions to file"""
        try:
            os.makedirs("logs", exist_ok=True)
            data = {
                "sessions": {
                    str(uid): asdict(session)
                    for uid, session in self._sessions.items()
                }
            }
            
            with open(self.AUTH_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving sessions: {e}")
    
    def start_login(self, user_id: int, account_type: str) -> Dict[str, Any]:
        """
        Start login process for user
        
        Args:
            user_id: Telegram user ID
            account_type: "demo" or "real"
            
        Returns:
            Status dict with success/error
        """
        with self._lock:
            # Check lockout
            if self._is_locked_out(user_id):
                remaining = self._get_lockout_remaining(user_id)
                return {
                    "success": False,
                    "error": "locked_out",
                    "remaining_seconds": remaining
                }
            
            # Set pending login
            self._pending_logins[user_id] = {
                "account_type": account_type,
                "timestamp": time.time()
            }
            
            return {
                "success": True,
                "message": "waiting_for_token",
                "account_type": account_type
            }
    
    def submit_token(self, user_id: int, token: str, language: str = "id") -> Dict[str, Any]:
        """
        Submit token to complete login
        
        Args:
            user_id: Telegram user ID
            token: Deriv API token
            language: User language preference
            
        Returns:
            Status dict with success/error
        """
        with self._lock:
            # Check if login was started
            pending = self._pending_logins.get(user_id)
            if not pending:
                return {"success": False, "error": "no_pending_login"}
            
            # Check pending timeout
            if time.time() - pending["timestamp"] > self.PENDING_TIMEOUT:
                del self._pending_logins[user_id]
                return {"success": False, "error": "login_timeout"}
            
            # Validate token format
            if not self._validate_token_format(token):
                self._record_failed_attempt(user_id)
                return {"success": False, "error": "invalid_token_format"}
            
            # Encrypt token
            encrypted = self._encrypt_token(token)
            fingerprint = self._create_fingerprint(token)
            
            # Create session
            session = UserSession(
                user_id=user_id,
                token_encrypted=encrypted,
                token_fingerprint=fingerprint,
                account_type=pending["account_type"],
                language=language,
                login_time=time.time(),
                last_activity=time.time()
            )
            
            self._sessions[user_id] = session
            del self._pending_logins[user_id]
            
            # Reset login attempts
            self._login_attempts.pop(user_id, None)
            
            # Save to file
            self._save_sessions()
            
            logger.info(f"User {user_id} logged in ({pending['account_type']})")
            
            return {
                "success": True,
                "account_type": pending["account_type"],
                "fingerprint": fingerprint[:8]  # First 8 chars for display
            }
    
    def logout(self, user_id: int) -> bool:
        """Logout user and clear session"""
        with self._lock:
            if user_id in self._sessions:
                del self._sessions[user_id]
                self._save_sessions()
                logger.info(f"User {user_id} logged out")
                return True
            return False
    
    def get_token(self, user_id: int) -> Optional[str]:
        """Get decrypted token for user"""
        with self._lock:
            session = self._sessions.get(user_id)
            if not session:
                return None
            
            # Update last activity
            session.last_activity = time.time()
            
            return self._decrypt_token(session.token_encrypted)
    
    def get_session(self, user_id: int) -> Optional[UserSession]:
        """Get user session"""
        return self._sessions.get(user_id)
    
    def is_logged_in(self, user_id: int) -> bool:
        """Check if user is logged in"""
        return user_id in self._sessions
    
    def get_account_type(self, user_id: int) -> Optional[str]:
        """Get user's account type"""
        session = self._sessions.get(user_id)
        return session.account_type if session else None
    
    def set_language(self, user_id: int, language: str):
        """Set user language preference"""
        with self._lock:
            session = self._sessions.get(user_id)
            if session:
                session.language = language
                self._save_sessions()
    
    def get_language(self, user_id: int) -> str:
        """Get user language preference"""
        session = self._sessions.get(user_id)
        return session.language if session else "id"
    
    def has_pending_login(self, user_id: int) -> bool:
        """Check if user has pending login"""
        pending = self._pending_logins.get(user_id)
        if not pending:
            return False
        
        # Check timeout
        if time.time() - pending["timestamp"] > self.PENDING_TIMEOUT:
            del self._pending_logins[user_id]
            return False
        
        return True
    
    def cancel_pending_login(self, user_id: int):
        """Cancel pending login"""
        self._pending_logins.pop(user_id, None)
    
    def _validate_token_format(self, token: str) -> bool:
        """Validate token format"""
        if not token:
            return False
        
        # Token should be 15-100 chars (Deriv tokens can be longer)
        if not 15 <= len(token) <= 100:
            return False
        
        # Deriv API tokens can contain alphanumeric, dashes, and underscores
        import re
        if not re.match(r'^[A-Za-z0-9_-]+$', token):
            return False
        
        return True
    
    def _encrypt_token(self, token: str) -> str:
        """Encrypt token"""
        encrypted = self._fernet.encrypt(token.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    
    def _decrypt_token(self, encrypted: str) -> Optional[str]:
        """Decrypt token"""
        try:
            data = base64.urlsafe_b64decode(encrypted.encode())
            decrypted = self._fernet.decrypt(data)
            return decrypted.decode()
        except Exception as e:
            logger.error(f"Token decryption error: {e}")
            return None
    
    def _create_fingerprint(self, token: str) -> str:
        """Create SHA-256 fingerprint of token"""
        return hashlib.sha256(token.encode()).hexdigest()
    
    def _is_locked_out(self, user_id: int) -> bool:
        """Check if user is locked out"""
        attempts = self._login_attempts.get(user_id)
        if not attempts:
            return False
        
        lockout_until = attempts.get("lockout_until", 0)
        if time.time() < lockout_until:
            return True
        
        # Lockout expired, reset
        if lockout_until > 0:
            del self._login_attempts[user_id]
        
        return False
    
    def _get_lockout_remaining(self, user_id: int) -> int:
        """Get remaining lockout time in seconds"""
        attempts = self._login_attempts.get(user_id)
        if not attempts:
            return 0
        
        lockout_until = attempts.get("lockout_until", 0)
        remaining = lockout_until - time.time()
        return max(0, int(remaining))
    
    def _record_failed_attempt(self, user_id: int):
        """Record failed login attempt"""
        attempts = self._login_attempts.get(user_id, {"count": 0, "lockout_until": 0})
        attempts["count"] += 1
        
        if attempts["count"] >= self.MAX_LOGIN_ATTEMPTS:
            attempts["lockout_until"] = time.time() + self.LOCKOUT_DURATION
            logger.warning(f"User {user_id} locked out after {attempts['count']} failed attempts")
        
        self._login_attempts[user_id] = attempts
    
    def clear_invalid_session(self, user_id: int):
        """Clear session if token is invalid"""
        with self._lock:
            if user_id in self._sessions:
                del self._sessions[user_id]
                self._save_sessions()
                logger.info(f"Cleared invalid session for user {user_id}")
    
    def reset_all(self):
        """Clear all sessions from memory (for fresh start)"""
        with self._lock:
            self._sessions.clear()
            self._pending_logins.clear()
            self._login_attempts.clear()
            logger.info("All user sessions cleared from memory")


# Global instance
user_auth = UserAuth()
