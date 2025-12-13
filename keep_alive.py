"""
Keep-Alive Service for Koyeb Free Tier
Self-pings to prevent the app from sleeping
"""

import os
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class KeepAliveService:
    """Self-ping service to keep Koyeb free tier app running 24/7"""
    
    def __init__(self, interval_seconds: int = 300):
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_ping: Optional[str] = None
        self.ping_count = 0
        self.app_url = os.environ.get("APP_URL", "")
        
    async def start(self):
        """Start the keep-alive service"""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._ping_loop())
        logger.info(f"Keep-alive service started (interval: {self.interval}s)")
        
    async def stop(self):
        """Stop the keep-alive service"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Keep-alive service stopped")
        
    async def _ping_loop(self):
        """Background loop to ping the app"""
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                await self._do_ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Keep-alive ping error: {e}")
                await asyncio.sleep(60)
                
    async def _do_ping(self):
        """Perform the ping request"""
        if not self.app_url:
            self.app_url = os.environ.get("APP_URL", "")
            if not self.app_url:
                koyeb_app = os.environ.get("KOYEB_PUBLIC_DOMAIN", "")
                if koyeb_app:
                    self.app_url = f"https://{koyeb_app}"
        
        if not self.app_url:
            if self.ping_count == 0:
                logger.warning("Keep-alive: APP_URL or KOYEB_PUBLIC_DOMAIN not set. "
                             "Set APP_URL=https://your-app.koyeb.app for 24/7 operation.")
            return
            
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(f"{self.app_url}/api/health")
                
                if response.status_code == 200:
                    self.ping_count += 1
                    self.last_ping = datetime.now().isoformat()
                    logger.info(f"Keep-alive ping #{self.ping_count} successful")
                else:
                    logger.warning(f"Keep-alive ping returned status {response.status_code}")
                    
        except Exception as e:
            logger.error(f"Keep-alive ping failed: {e}")
            
    def get_status(self) -> dict:
        """Get keep-alive service status"""
        return {
            "running": self._running,
            "interval_seconds": self.interval,
            "ping_count": self.ping_count,
            "last_ping": self.last_ping,
            "app_url": self.app_url or "not configured"
        }


keep_alive_service = KeepAliveService(interval_seconds=240)
