"""
Chat Mapping - User to chat ID mapping for Telegram notifications
"""

import os
import json
import logging
import threading
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

class ChatMapping:
    """
    Manages mapping between Telegram user IDs and chat IDs
    
    Persists mappings for reliable message delivery across restarts.
    """
    
    MAPPING_FILE = "logs/chat_mapping.json"
    
    def __init__(self):
        self._mapping: Dict[int, int] = {}  # user_id -> chat_id
        self._active_chats: Set[int] = set()  # Active chat IDs
        self._lock = threading.RLock()
        
        self._load_mapping()
    
    def _load_mapping(self):
        """Load mapping from file"""
        if not os.path.exists(self.MAPPING_FILE):
            return
        
        try:
            with open(self.MAPPING_FILE, 'r') as f:
                data = json.load(f)
            
            self._mapping = {int(k): v for k, v in data.get("mapping", {}).items()}
            self._active_chats = set(data.get("active_chats", []))
            
            logger.info(f"Loaded {len(self._mapping)} chat mappings")
        except Exception as e:
            logger.error(f"Error loading chat mapping: {e}")
    
    def _save_mapping(self):
        """Save mapping to file"""
        try:
            os.makedirs("logs", exist_ok=True)
            data = {
                "mapping": self._mapping,
                "active_chats": list(self._active_chats)
            }
            
            with open(self.MAPPING_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving chat mapping: {e}")
    
    def set_chat_id(self, user_id: int, chat_id: int):
        """Set chat ID for a user"""
        with self._lock:
            self._mapping[user_id] = chat_id
            self._active_chats.add(chat_id)
            self._save_mapping()
    
    def get_chat_id(self, user_id: int) -> Optional[int]:
        """Get chat ID for a user"""
        return self._mapping.get(user_id)
    
    def remove_user(self, user_id: int):
        """Remove user from mapping"""
        with self._lock:
            chat_id = self._mapping.pop(user_id, None)
            if chat_id:
                # Check if any other user uses this chat
                if chat_id not in self._mapping.values():
                    self._active_chats.discard(chat_id)
            self._save_mapping()
    
    def is_active_chat(self, chat_id: int) -> bool:
        """Check if chat is active"""
        return chat_id in self._active_chats
    
    def get_all_active_chats(self) -> Set[int]:
        """Get all active chat IDs"""
        return self._active_chats.copy()
    
    def get_user_for_chat(self, chat_id: int) -> Optional[int]:
        """Get user ID for a chat ID"""
        for user_id, cid in self._mapping.items():
            if cid == chat_id:
                return user_id
        return None


# Global instance
chat_mapping = ChatMapping()
