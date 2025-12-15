"""
Telegram Bot - Main bot interface with WebApp integration
"""

import os
import logging
import asyncio
import time
import hashlib
import threading
import httpx
import html
from typing import Dict, Any, Optional, Union, cast
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, User, CallbackQuery, Message
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode

from user_auth import user_auth
from chat_mapping import chat_mapping
from i18n import get_text, detect_language, set_user_language, get_user_language, SUPPORTED_LANGUAGES
from symbols import get_symbol_list_text, get_short_term_symbols, get_symbol_config
from deriv_ws import DerivWebSocket
from trading import TradingManager, TradingConfig, TradingState, StrategyType
from strategy_config import get_strategy_config, StrategyName

logger = logging.getLogger(__name__)

_webapp_manager = None

def set_webapp_manager(manager):
    """Set the WebApp ConnectionManager reference for broadcasting trade events"""
    global _webapp_manager
    _webapp_manager = manager

def get_webapp_manager():
    """Get the WebApp ConnectionManager reference"""
    return _webapp_manager


# Strategy configurations with WebApp routes
STRATEGIES = {
    "TERMINAL": {
        "name": "Terminal Pro",
        "icon": "⚡",
        "description": "Smart Analysis 80% Probability",
        "webapp_route": "/terminal"
    },
    "TICK_PICKER": {
        "name": "Tick Picker", 
        "icon": "📈",
        "description": "Tick Pattern Analysis",
        "webapp_route": "/tick-picker"
    },
    "DIGITPAD": {
        "name": "DigitPad",
        "icon": "🔢",
        "description": "Digit Frequency Heatmap",
        "webapp_route": "/digitpad"
    },
    "AMT": {
        "name": "AMT Accumulator",
        "icon": "📊",
        "description": "Growth Rate Management",
        "webapp_route": "/amt"
    },
    "SNIPER": {
        "name": "Sniper",
        "icon": "🎯",
        "description": "High Probability Only (80%+)",
        "webapp_route": "/sniper"
    },
    "LDP": {
        "name": "LDP Analyzer",
        "icon": "🎲",
        "description": "Last Digit Prediction",
        "webapp_route": "/ldp"
    },
    "MULTI_INDICATOR": {
        "name": "Multi-Indicator",
        "icon": "📉",
        "description": "RSI, EMA, MACD, Stochastic, ADX",
        "webapp_route": "/multi-indicator"
    },
    "TICK_ANALYZER": {
        "name": "Tick Analyzer",
        "icon": "📊",
        "description": "Tick Pattern Analysis",
        "webapp_route": "/tick-picker"
    }
}


class TelegramBot:
    """
    Telegram Bot for Deriv Auto Trading with WebApp Integration
    
    Features:
    - Interactive commands and callback queries
    - Per-user session management
    - Real-time trading notifications
    - WebApp integration for each strategy
    - Multi-language support
    """
    
    MESSAGE_RATE_LIMIT = 1.0
    DEDUP_TTL = 60
    
    def __init__(self, token: str, webapp_base_url: Optional[str] = None):
        self.token = token
        self.webapp_base_url: str = webapp_base_url or os.environ.get("WEBAPP_BASE_URL", "https://your-domain.com")
        self.application: Optional[Application] = None
        
        # Per-user WebSocket and trading managers
        self._ws_connections: Dict[int, DerivWebSocket] = {}
        self._trading_managers: Dict[int, TradingManager] = {}
        self._user_strategies: Dict[int, str] = {}  # user_id -> selected strategy
        
        # Message deduplication
        self._sent_messages: Dict[str, float] = {}
        self._last_message_time: Dict[int, float] = {}
        
        # Lock for thread safety
        self._lock = threading.RLock()
        
        # User context storage
        self._user_context: Dict[str, Any] = {}
    
    async def start(self):
        """Start the Telegram bot with proper cleanup to prevent conflicts"""
        self.application = Application.builder().token(self.token).build()
        self._register_handlers()
        
        await self.application.initialize()
        await self.application.start()
        
        # CRITICAL: drop_pending_updates prevents "Conflict: terminated by other getUpdates request" error
        # This happens when multiple bot instances or stale webhook requests exist
        if self.application.updater is not None:
            await self.application.updater.start_polling(
                drop_pending_updates=True,  # Clear old updates to prevent conflicts
                allowed_updates=["message", "callback_query", "inline_query"]  # Only listen to what we need
            )
        
        logger.info("Telegram bot started with drop_pending_updates=True")
    
    async def stop(self):
        """Stop the Telegram bot gracefully"""
        logger.info("Stopping Telegram bot gracefully...")
        
        # First stop all trading managers to prevent orphaned trades
        for user_id, tm in list(self._trading_managers.items()):
            try:
                tm.stop()
                logger.info(f"Stopped trading manager for user {user_id}")
            except Exception as e:
                logger.error(f"Error stopping trading manager for {user_id}: {e}")
        self._trading_managers.clear()
        
        # Disconnect all WebSocket connections
        for user_id, ws in list(self._ws_connections.items()):
            try:
                ws.disconnect()
                logger.info(f"Disconnected WebSocket for user {user_id}")
            except Exception as e:
                logger.error(f"Error disconnecting WebSocket for {user_id}: {e}")
        self._ws_connections.clear()
        
        # Stop the Telegram application with proper order
        if self.application:
            try:
                # Stop updater first (stops polling)
                if self.application.updater and self.application.updater.running:
                    await self.application.updater.stop()
                    logger.info("Telegram updater stopped")
                
                # Then stop application
                await self.application.stop()
                logger.info("Telegram application stopped")
                
                # Finally shutdown
                await self.application.shutdown()
                logger.info("Telegram application shutdown complete")
            except Exception as e:
                logger.error(f"Error during Telegram bot shutdown: {e}")
        
        logger.info("Telegram bot stopped successfully")
    
    def _register_handlers(self) -> None:
        """Register command and callback handlers"""
        assert self.application is not None, "Application must be initialized before registering handlers"
        app = self.application
        
        # Commands
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("login", self._cmd_login))
        app.add_handler(CommandHandler("logout", self._cmd_logout))
        app.add_handler(CommandHandler("akun", self._cmd_account))
        app.add_handler(CommandHandler("autotrade", self._cmd_autotrade))
        app.add_handler(CommandHandler("stop", self._cmd_stop))
        app.add_handler(CommandHandler("status", self._cmd_status))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("strategi", self._cmd_strategy))
        app.add_handler(CommandHandler("pair", self._cmd_pair))
        app.add_handler(CommandHandler("language", self._cmd_language))
        app.add_handler(CommandHandler("webapp", self._cmd_webapp))
        app.add_handler(CommandHandler("reset_breach", self._cmd_reset_breach))
        
        # Callback queries
        app.add_handler(CallbackQueryHandler(self._handle_callback))
        
        # Message handler for token input
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_message
        ))
    
    def _get_webapp_url(self, user_id: int, strategy: Optional[str] = None) -> str:
        """Get WebApp URL for user's selected strategy"""
        if strategy is None:
            strategy = self._user_strategies.get(user_id, "TERMINAL")
        
        route = STRATEGIES.get(strategy, {}).get("webapp_route", "/terminal")
        return f"{self.webapp_base_url}{route}"
    
    async def _notify_webapp_strategy_change(self, user_id: int, strategy: str):
        """Notify web server about strategy change"""
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.webapp_base_url}/api/telegram/set-strategy",
                    params={"telegram_id": user_id, "strategy": strategy}
                )
        except Exception as e:
            logger.error(f"Failed to notify webapp: {e}")
    
    # ==================== Commands ====================
    
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        user = update.effective_user
        chat = update.effective_chat
        if user is None or chat is None:
            return
        chat_id = chat.id
        
        lang = detect_language(user.language_code)
        set_user_language(user.id, lang)
        chat_mapping.set_chat_id(user.id, chat_id)
        
        if user_auth.is_logged_in(user.id):
            await self._show_main_menu(update, context)
        else:
            await self._show_welcome(update, context)
    
    async def _show_welcome(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show welcome screen with login options"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        lang = get_user_language(user.id)
        
        escaped_name = html.escape(user.first_name)
        text = f"""
🤖 <b>Deriv Auto Trading Bot</b>

Selamat datang, {escaped_name}!

Bot ini membantu Anda trading di Deriv dengan berbagai strategi otomatis:

⚡ <b>Terminal</b> - Smart Analysis 80%
📈 <b>Tick Picker</b> - Pattern Analysis
🔢 <b>DigitPad</b> - Digit Frequency
📊 <b>AMT</b> - Accumulator
🎯 <b>Sniper</b> - High Probability

Silakan login untuk memulai:
"""
        
        keyboard = [
            [
                InlineKeyboardButton("🔵 Demo Account", callback_data="login_demo"),
                InlineKeyboardButton("🟢 Real Account", callback_data="login_real")
            ],
            [InlineKeyboardButton("📖 Panduan", callback_data="menu_help")]
        ]
        
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show main menu after login"""
        user = update.effective_user
        if user is None:
            return
        lang = get_user_language(user.id)
        
        ws = self._ws_connections.get(user.id)
        balance = ws.get_balance() if ws and ws.is_connected() else 0
        currency = ws.get_currency() if ws and ws.is_connected() else "USD"
        account_type = user_auth.get_account_type(user.id) or "demo"
        
        selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
        strategy_info = STRATEGIES.get(selected_strategy, {})
        
        escaped_currency = html.escape(currency)
        escaped_strategy_name = html.escape(strategy_info.get('name', selected_strategy))
        
        text = f"""
🏠 <b>Menu Utama</b>

👤 Account: {account_type.upper()}
💰 Balance: {balance:.2f} {escaped_currency}
📊 Strategy: {strategy_info.get('icon', '')} {escaped_strategy_name}

Pilih menu:
"""
        
        # Create WebApp button for current strategy
        webapp_url = self._get_webapp_url(user.id, selected_strategy)
        
        keyboard = [
            [InlineKeyboardButton(
                f"🌐 Buka {strategy_info.get('name', 'WebApp')}",
                web_app=WebAppInfo(url=webapp_url)
            )],
            [
                InlineKeyboardButton("📊 Pilih Strategi", callback_data="menu_strategy"),
                InlineKeyboardButton("💱 Pilih Pair", callback_data="menu_pair")
            ],
            [
                InlineKeyboardButton("▶️ Auto Trade", callback_data="menu_autotrade"),
                InlineKeyboardButton("📈 Status", callback_data="menu_status")
            ],
            [
                InlineKeyboardButton("👤 Akun", callback_data="menu_account"),
                InlineKeyboardButton("🌍 Bahasa", callback_data="menu_language")
            ],
            [InlineKeyboardButton("🚪 Logout", callback_data="confirm_logout")]
        ]
        
        if update.message:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def _cmd_strategy(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /strategi command - Show strategy selection"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        selected = self._user_strategies.get(user.id, "TERMINAL")
        
        escaped_strategy_name = html.escape(STRATEGIES.get(selected, {}).get('name', selected))
        text = f"""
📊 <b>Pilih Strategi Trading</b>

Strategi saat ini: {STRATEGIES.get(selected, {}).get('icon', '')} {escaped_strategy_name}

Pilih strategi yang ingin digunakan:
"""
        
        keyboard = []
        for key, info in STRATEGIES.items():
            mark = "✅ " if key == selected else ""
            keyboard.append([
                InlineKeyboardButton(
                    f"{mark}{info['icon']} {info['name']}",
                    callback_data=f"strategy_{key}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")])
        
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_webapp(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /webapp command - Open WebApp"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        
        if not user_auth.is_logged_in(user.id):
            await message.reply_text("❌ Silakan login terlebih dahulu dengan /login")
            return
        
        selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
        strategy_info = STRATEGIES.get(selected_strategy, {})
        webapp_url = self._get_webapp_url(user.id, selected_strategy)
        
        escaped_name = html.escape(strategy_info.get('name', ''))
        escaped_desc = html.escape(strategy_info.get('description', ''))
        text = f"""
🌐 <b>WebApp {escaped_name}</b>

{strategy_info.get('icon', '')} {escaped_desc}

Klik tombol di bawah untuk membuka WebApp:
"""
        
        keyboard = [[
            InlineKeyboardButton(
                f"🚀 Buka {strategy_info.get('name', 'WebApp')}",
                web_app=WebAppInfo(url=webapp_url)
            )
        ]]
        
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_reset_breach(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /reset_breach command - Clear breach state to resume trading"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        
        if user.id not in self._trading_managers:
            await message.reply_text("⚠️ Tidak ada sesi trading aktif. Silakan login dulu dengan /login")
            return
        
        tm = self._trading_managers[user.id]
        if hasattr(tm, 'money_manager') and tm.money_manager:
            is_breached, reason = tm.money_manager.is_breached()
            if is_breached:
                tm.money_manager.clear_breach()
                await message.reply_text(
                    f"✅ <b>Breach State Dihapus</b>\n\n"
                    f"Alasan sebelumnya: {html.escape(reason)}\n\n"
                    f"Trading dapat dilanjutkan kembali.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.reply_text("ℹ️ Tidak ada breach state aktif.")
        else:
            await message.reply_text("⚠️ Money manager tidak tersedia.")
    
    async def _cmd_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /login command"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        lang = get_user_language(user.id)
        
        if user_auth.is_logged_in(user.id):
            await message.reply_text(
                "✅ Anda sudah login. Gunakan /logout untuk keluar terlebih dahulu."
            )
            return
        
        keyboard = [
            [
                InlineKeyboardButton("🔵 Demo", callback_data="login_demo"),
                InlineKeyboardButton("🟢 Real", callback_data="login_real")
            ]
        ]
        
        await message.reply_text(
            "🔐 <b>Login ke Deriv</b>\n\nPilih tipe akun:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /logout command"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        
        if user.id in self._trading_managers:
            self._trading_managers[user.id].stop()
            del self._trading_managers[user.id]
        
        if user.id in self._ws_connections:
            self._ws_connections[user.id].disconnect()
            del self._ws_connections[user.id]
        
        # Clear session_manager data
        try:
            from web_server import session_manager, unregister_deriv_connection
            session_manager.clear_user_data(user.id)
            unregister_deriv_connection(user.id)
        except Exception as e:
            logger.error(f"Failed to clear session_manager for user {user.id}: {e}")
        
        user_auth.logout(user.id)
        
        await message.reply_text("✅ Berhasil logout. Sampai jumpa!")
    
    async def _cmd_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /akun command"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        
        if not user_auth.is_logged_in(user.id):
            await message.reply_text("❌ Silakan login terlebih dahulu dengan /login")
            return
        
        ws = self._ws_connections.get(user.id)
        if not ws or not ws.is_connected():
            await message.reply_text("❌ Tidak terhubung ke Deriv. Silakan login ulang.")
            return
        
        account_type = user_auth.get_account_type(user.id) or "unknown"
        balance = ws.get_balance()
        currency = ws.get_currency()
        
        escaped_currency = html.escape(currency)
        escaped_loginid = html.escape(ws.loginid or 'N/A')
        text = f"""
👤 <b>Info Akun</b>

📋 Tipe: {account_type.upper()}
💰 Saldo: {balance:.2f} {escaped_currency}
🆔 Login ID: {escaped_loginid}
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Switch Account", callback_data="switch_account")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
        ]
        
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_autotrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /autotrade command"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        
        if not user_auth.is_logged_in(user.id):
            await message.reply_text("❌ Silakan login terlebih dahulu dengan /login")
            return
        
        if user.id in self._trading_managers:
            tm = self._trading_managers[user.id]
            if tm.state == TradingState.RUNNING:
                keyboard = [
                    [InlineKeyboardButton("⏹️ Stop Trading", callback_data="confirm_stop_trading")],
                    [InlineKeyboardButton("🔄 Force Restart", callback_data="force_restart_trading")],
                    [InlineKeyboardButton("🔙 Menu", callback_data="menu_main")]
                ]
                await message.reply_text(
                    "⚠️ <b>Trading sedang berjalan</b>\n\n"
                    "Pilih aksi:\n"
                    "• <b>Stop Trading</b> - Hentikan trading saat ini\n"
                    "• <b>Force Restart</b> - Stop paksa dan mulai ulang",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
        
        await self._show_trading_setup(update, context)
    
    async def _show_trading_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show trading setup menu"""
        user = update.effective_user
        if user is None:
            return
        
        selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
        selected_symbol = self._user_context.get(f"selected_symbol_{user.id}", "R_100")
        
        # Get strategy config for default stake
        strategy_config = get_strategy_config(selected_strategy)
        default_stake = strategy_config.default_stake if strategy_config else 1.00
        selected_stake = self._user_context.get(f"selected_stake_{user.id}", default_stake)
        
        # Get trade count setting
        trade_count = self._user_context.get(f"trade_count_{user.id}", 10)
        trade_count_display = "∞ Unlimited" if trade_count == 0 else str(trade_count)
        
        strategy_info = STRATEGIES.get(selected_strategy, {})
        
        strategy_name = html.escape(strategy_info.get('name', selected_strategy))
        strategy_icon = strategy_info.get('icon', '')
        
        text = f"""⚙️ <b>Pengaturan Auto Trade</b>

📊 Strategi: {strategy_icon} {strategy_name}
💱 Pair: {html.escape(selected_symbol)}
💵 Stake: <b>${selected_stake:.2f}</b>
🎯 Target: <b>{trade_count_display} trades</b>

Klik tombol di bawah untuk memulai:"""
        
        keyboard = [
            [InlineKeyboardButton("📊 Ubah Strategi", callback_data="menu_strategy")],
            [InlineKeyboardButton("💱 Ubah Pair", callback_data="menu_pair")],
            [InlineKeyboardButton("💵 Ubah Stake", callback_data=f"change_stake_{selected_strategy}")],
            [InlineKeyboardButton("🎯 Ubah Jumlah Trade", callback_data="menu_trade_count")],
            [InlineKeyboardButton("▶️ MULAI TRADING", callback_data="confirm_start_trading")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
        ]
        
        if update.message:
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stop command"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        
        if user.id not in self._trading_managers:
            await message.reply_text("❌ Tidak ada trading yang berjalan.")
            return
        
        tm = self._trading_managers[user.id]
        
        # Get stats before stopping
        status = tm.get_status()
        wins = status.get("wins", 0)
        losses = status.get("losses", 0)
        total_trades = status.get("trades", 0)
        win_rate = status.get("win_rate", 0)
        session_profit = status.get("session_profit", 0)
        balance = status.get("balance", 0)
        strategy = status.get("strategy", "N/A")
        
        tm.stop()
        
        # Format stop message with stats
        profit_emoji = "📈" if session_profit >= 0 else "📉"
        profit_color = "+" if session_profit >= 0 else ""
        
        stop_message = f"""⏹️ <b>Trading Dihentikan</b>

📊 <b>Ringkasan Sesi:</b>
├ Strategi: {strategy}
├ Total Trade: {total_trades}
├ ✅ Win: {wins}
├ ❌ Lose: {losses}
├ 📊 Winrate: {win_rate:.1f}%
└ {profit_emoji} Profit: {profit_color}${session_profit:.2f}

💰 Balance: ${balance:.2f}

Gunakan /strategi untuk trading lagi."""
        
        await message.reply_text(stop_message, parse_mode=ParseMode.HTML)
    
    def force_stop_trading(self, user_id: int) -> Dict[str, Any]:
        """
        Force stop trading for a user - can be called from web_server
        This method completely clears trading state to avoid stuck issues
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Dict with success status and message
        """
        try:
            if user_id not in self._trading_managers:
                # Also check web_server in case it was started via API
                try:
                    from web_server import unregister_trading_manager
                    unregister_trading_manager(user_id)
                except:
                    pass
                return {
                    "success": True,
                    "message": "No trading manager found",
                    "was_running": False
                }
            
            tm = self._trading_managers[user_id]
            was_running = tm.state == TradingState.RUNNING
            
            # Force stop regardless of state
            try:
                tm.stop()
            except Exception as e:
                logger.error(f"Error during force stop for user {user_id}: {e}")
            
            # Force state to IDLE
            tm.state = TradingState.IDLE
            
            # Remove from dict to ensure fresh start next time
            del self._trading_managers[user_id]
            
            # Unregister from web_server
            try:
                from web_server import unregister_trading_manager
                unregister_trading_manager(user_id)
            except Exception as e:
                logger.error(f"Failed to unregister from web_server: {e}")
            
            logger.info(f"Force stopped trading for user {user_id} (was_running: {was_running})")
            
            return {
                "success": True,
                "message": "Trading force stopped",
                "was_running": was_running
            }
            
        except Exception as e:
            logger.error(f"Force stop failed for user {user_id}: {e}")
            return {
                "success": False,
                "message": str(e),
                "was_running": False
            }
    
    def get_trading_state(self, user_id: int) -> Optional[str]:
        """Get current trading state for a user"""
        if user_id not in self._trading_managers:
            return None
        return self._trading_managers[user_id].state.value
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        
        if not user_auth.is_logged_in(user.id):
            await message.reply_text("❌ Silakan login terlebih dahulu.")
            return
        
        if user.id not in self._trading_managers:
            selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
            strategy_info = STRATEGIES.get(selected_strategy, {})
            
            await message.reply_text(
                f"💤 Status: IDLE\n📊 Strategi: {strategy_info.get('icon', '')} {strategy_info.get('name', '')}\n\nGunakan /autotrade untuk memulai."
            )
            return
        
        tm = self._trading_managers[user.id]
        status = tm.get_status()
        
        escaped_state = html.escape(str(status['state']))
        escaped_symbol = html.escape(str(status['symbol']))
        escaped_strategy = html.escape(str(status['strategy']))
        text = f"""
📊 <b>Status Trading</b>

🔄 State: {escaped_state}
💱 Symbol: {escaped_symbol}
📈 Strategi: {escaped_strategy}
🎯 Trades: {status['session_trades']}/{status['target_trades']}
💰 Profit: ${status['session_profit']:.2f}
📉 Win Rate: {status['win_rate']:.1f}%
"""
        
        await message.reply_text(text, parse_mode=ParseMode.HTML)
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        message = update.message
        if message is None:
            return
        text = """
📖 <b>Panduan Deriv Auto Trading Bot</b>

<b>Perintah:</b>
/start - Memulai bot
/login - Login ke akun Deriv
/logout - Keluar dari akun
/akun - Info akun dan saldo
/strategi - Pilih strategi trading
/webapp - Buka WebApp
/autotrade - Mulai auto trading
/stop - Hentikan trading
/status - Status trading
/pair - Pilih pair/symbol
/language - Ubah bahasa
/help - Panduan ini

<b>Strategi Tersedia:</b>
⚡ Terminal - Smart Analysis 80%
📈 Tick Picker - Pattern Analysis
🔢 DigitPad - Digit Frequency
📊 AMT - Accumulator
🎯 Sniper - High Probability

<b>Tips:</b>
• Gunakan Demo account untuk testing
• Pilih strategi sesuai gaya trading
• Monitor win rate Anda
• Gunakan WebApp untuk kontrol lebih
"""
        
        await message.reply_text(text, parse_mode=ParseMode.HTML)
    
    async def _cmd_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /pair command"""
        user = update.effective_user
        message = update.message
        if user is None or message is None:
            return
        symbols = get_short_term_symbols()
        selected = self._user_context.get(f"selected_symbol_{user.id}", "R_100")
        
        keyboard = []
        row = []
        for symbol in symbols:
            mark = "✅ " if symbol == selected else ""
            row.append(InlineKeyboardButton(f"{mark}{symbol}", callback_data=f"symbol_{symbol}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")])
        
        await message.reply_text(
            "💱 <b>Pilih Pair Trading:</b>\n\n" + html.escape(get_symbol_list_text()),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /language command"""
        message = update.message
        if message is None:
            return
        keyboard = []
        row = []
        
        for code, name in list(SUPPORTED_LANGUAGES.items())[:12]:
            row.append(InlineKeyboardButton(f"{name}", callback_data=f"lang_{code}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")])
        
        await message.reply_text(
            "🌍 <b>Pilih Bahasa / Select Language:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ==================== Callback Handlers ====================
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle callback queries"""
        query = update.callback_query
        user = update.effective_user
        if query is None or user is None:
            return
        await query.answer()
        
        data = query.data
        if data is None:
            return
        
        if data.startswith("login_"):
            await self._handle_login_callback(query, user, data)
        elif data.startswith("strategy_"):
            await self._handle_strategy_callback(query, user, data)
        elif data.startswith("stake_"):
            await self._handle_stake_callback(query, user, data)
        elif data.startswith("change_stake_"):
            strategy = data.replace("change_stake_", "")
            await self._show_stake_selection(query, user, strategy)
        elif data.startswith("symbol_"):
            await self._handle_symbol_callback(query, user, data)
        elif data.startswith("lang_"):
            await self._handle_language_callback(query, user, data)
        elif data.startswith("set_trade_count_"):
            await self._handle_trade_count_callback(query, user, data)
        elif data.startswith("menu_"):
            await self._handle_menu_callback(query, user, data, context)
        elif data.startswith("confirm_"):
            await self._handle_confirm_callback(query, user, data, context)
        elif data == "force_restart_trading":
            await self._handle_force_restart_trading(query, user, context)
        elif data == "switch_account":
            await self._handle_switch_account(query, user)
    
    async def _handle_login_callback(self, query: CallbackQuery, user: User, data: str) -> None:
        """Handle login callbacks"""
        account_type = data.replace("login_", "")
        
        result = user_auth.start_login(user.id, account_type)
        
        if result["success"]:
            await query.edit_message_text(
                f"🔐 <b>Login {account_type.upper()}</b>\n\n"
                "Silakan kirim API Token Deriv Anda.\n\n"
                "💡 Dapatkan token di: https://app.deriv.com/account/api-token\n\n"
                "⚠️ Pesan ini akan dihapus setelah token diterima.",
                parse_mode=ParseMode.HTML
            )
        else:
            if result.get("error") == "locked_out":
                await query.edit_message_text(
                    f"⚠️ Akun terkunci. Coba lagi dalam {result['remaining_seconds']} detik."
                )
    
    async def _handle_strategy_callback(self, query: CallbackQuery, user: User, data: str) -> None:
        """Handle strategy selection - then show stake options"""
        strategy = data.replace("strategy_", "")
        
        if strategy not in STRATEGIES:
            await query.answer("Strategy tidak valid", show_alert=True)
            return
        
        self._user_strategies[user.id] = strategy
        
        # Notify webapp
        await self._notify_webapp_strategy_change(user.id, strategy)
        
        # Show stake selection after choosing strategy
        await self._show_stake_selection(query, user, strategy)
    
    async def _show_stake_selection(self, query: CallbackQuery, user: User, strategy: str) -> None:
        """Show stake selection options for the selected strategy"""
        strategy_info = STRATEGIES.get(strategy, {})
        strategy_config = get_strategy_config(strategy)
        
        if not strategy_config:
            # Fallback to default stakes if config not found
            stake_options = [
                {"value": 0.35, "label": "$0.35"},
                {"value": 0.50, "label": "$0.50"},
                {"value": 1.00, "label": "$1.00"},
                {"value": 2.00, "label": "$2.00"},
                {"value": 5.00, "label": "$5.00"},
                {"value": 10.00, "label": "$10.00"},
            ]
            default_stake = 1.00
        else:
            stake_options = [
                {"value": s.value, "label": s.label, "is_default": s.is_default} 
                for s in strategy_config.stake_options
            ]
            default_stake = strategy_config.default_stake
        
        # Get current selected stake or use default
        current_stake = self._user_context.get(f"selected_stake_{user.id}", default_stake)
        
        # Get min/max stake values
        min_stake = strategy_config.min_stake if strategy_config else 0.35
        max_stake = strategy_config.max_stake if strategy_config else 100.00
        
        escaped_name = html.escape(strategy_info.get('name', strategy))
        escaped_desc = html.escape(strategy_info.get('description', ''))
        text = f"""
💵 <b>Pilih Stake untuk Trading</b>

📊 Strategi: {strategy_info.get('icon', '')} <b>{escaped_name}</b>
{escaped_desc}

💡 Minimum stake: ${min_stake:.2f}
📈 Maximum stake: ${max_stake:.2f}

Pilih jumlah stake per trade:
"""
        
        keyboard = []
        row = []
        for opt in stake_options:
            mark = "✅ " if opt['value'] == current_stake else ""
            btn = InlineKeyboardButton(
                f"{mark}{opt['label']}",
                callback_data=f"stake_{strategy}_{opt['value']}"
            )
            row.append(btn)
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Ubah Strategi", callback_data="menu_strategy")])
        keyboard.append([InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_main")])
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _show_trade_count_selection(self, query: CallbackQuery, user: User) -> None:
        """Show trade count selection menu with unlimited option for demo testing"""
        current_count = self._user_context.get(f"trade_count_{user.id}", 10)
        
        text = """🎯 <b>Pilih Jumlah Trade</b>

Berapa banyak trade yang ingin dijalankan secara otomatis?

💡 <b>Unlimited</b> cocok untuk testing bot di akun demo!

Pilih jumlah trade:"""
        
        trade_count_options = [5, 10, 25, 50, 100, 0]  # 0 = unlimited
        
        keyboard = []
        row = []
        for count in trade_count_options:
            label = "∞ Unlimited" if count == 0 else str(count)
            mark = "✅ " if count == current_count else ""
            btn = InlineKeyboardButton(
                f"{mark}{label}",
                callback_data=f"set_trade_count_{count}"
            )
            row.append(btn)
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="menu_autotrade")])
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _handle_trade_count_callback(self, query: CallbackQuery, user: User, data: str) -> None:
        """Handle trade count selection"""
        try:
            count = int(data.replace("set_trade_count_", ""))
        except ValueError:
            await query.answer("Nilai tidak valid", show_alert=True)
            return
        
        self._user_context[f"trade_count_{user.id}"] = count
        
        # Also update trading manager if running
        if user.id in self._trading_managers:
            tm = self._trading_managers[user.id]
            tm.set_trade_count(count, unlimited=(count == 0))
        
        count_display = "∞ Unlimited" if count == 0 else str(count)
        await query.answer(f"✅ Target trade: {count_display}", show_alert=False)
        
        # Go back to trade count selection to show updated choice
        await self._show_trade_count_selection(query, user)
    
    async def _handle_stake_callback(self, query: CallbackQuery, user: User, data: str) -> None:
        """Handle stake selection"""
        # Parse stake data: stake_STRATEGY_VALUE
        parts = data.replace("stake_", "").rsplit("_", 1)
        if len(parts) != 2:
            await query.answer("Data stake tidak valid", show_alert=True)
            return
        
        strategy = parts[0]
        try:
            stake_value = float(parts[1])
        except ValueError:
            await query.answer("Nilai stake tidak valid", show_alert=True)
            return
        
        # Store selected stake
        self._user_context[f"selected_stake_{user.id}"] = stake_value
        
        strategy_info = STRATEGIES.get(strategy, {})
        webapp_url = self._get_webapp_url(user.id, strategy)
        
        escaped_name = html.escape(strategy_info.get('name', strategy))
        escaped_desc = html.escape(strategy_info.get('description', ''))
        text = f"""
✅ <b>Konfigurasi Trading</b>

📊 Strategi: {strategy_info.get('icon', '')} <b>{escaped_name}</b>
💵 Stake: <b>${stake_value:.2f}</b> per trade

{escaped_desc}

Klik tombol di bawah untuk mulai trading:
"""
        
        keyboard = [
            [InlineKeyboardButton("▶️ MULAI TRADING", callback_data="confirm_start_trading")],
            [InlineKeyboardButton(
                f"🌐 Buka {strategy_info.get('name', 'WebApp')}",
                web_app=WebAppInfo(url=webapp_url)
            )],
            [InlineKeyboardButton("💵 Ubah Stake", callback_data=f"change_stake_{strategy}")],
            [InlineKeyboardButton("📊 Ubah Strategi", callback_data="menu_strategy")],
            [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _handle_symbol_callback(self, query: CallbackQuery, user: User, data: str) -> None:
        """Handle symbol selection"""
        symbol = data.replace("symbol_", "")
        self._user_context[f"selected_symbol_{user.id}"] = symbol
        
        config = get_symbol_config(symbol)
        
        escaped_symbol = html.escape(symbol)
        escaped_config_name = html.escape(config.name) if config else ''
        await query.edit_message_text(
            f"✅ <b>Pair Dipilih: {escaped_symbol}</b>\n{escaped_config_name}\n\n"
            "Gunakan /autotrade untuk mulai trading.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
            ])
        )
    
    async def _handle_language_callback(self, query: CallbackQuery, user: User, data: str) -> None:
        """Handle language selection"""
        lang = data.replace("lang_", "")
        set_user_language(user.id, lang)
        
        await query.edit_message_text(
            f"✅ Bahasa diubah ke {SUPPORTED_LANGUAGES.get(lang, lang)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
            ])
        )
    
    async def _handle_menu_callback(self, query: CallbackQuery, user: User, data: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle menu navigation"""
        menu = data.replace("menu_", "")
        
        if menu == "main":
            # Edit message directly instead of using FakeUpdate
            ws = self._ws_connections.get(user.id)
            balance = ws.get_balance() if ws and ws.is_connected() else 0
            currency = ws.get_currency() if ws and ws.is_connected() else "USD"
            account_type = user_auth.get_account_type(user.id) or "demo"
            
            selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
            strategy_info = STRATEGIES.get(selected_strategy, {})
            
            escaped_currency = html.escape(currency)
            escaped_strategy_name = html.escape(strategy_info.get('name', selected_strategy))
            
            text = f"""
🏠 <b>Menu Utama</b>

👤 Account: {account_type.upper()}
💰 Balance: {balance:.2f} {escaped_currency}
📊 Strategy: {strategy_info.get('icon', '')} {escaped_strategy_name}

Pilih menu:
"""
            
            webapp_url = self._get_webapp_url(user.id, selected_strategy)
            
            keyboard = [
                [InlineKeyboardButton(
                    f"🌐 Buka {strategy_info.get('name', 'WebApp')}",
                    web_app=WebAppInfo(url=webapp_url)
                )],
                [
                    InlineKeyboardButton("📊 Pilih Strategi", callback_data="menu_strategy"),
                    InlineKeyboardButton("💱 Pilih Pair", callback_data="menu_pair")
                ],
                [
                    InlineKeyboardButton("▶️ Auto Trade", callback_data="menu_autotrade"),
                    InlineKeyboardButton("📈 Status", callback_data="menu_status")
                ],
                [
                    InlineKeyboardButton("👤 Akun", callback_data="menu_account"),
                    InlineKeyboardButton("🌍 Bahasa", callback_data="menu_language")
                ],
                [InlineKeyboardButton("🚪 Logout", callback_data="confirm_logout")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif menu == "strategy":
            selected = self._user_strategies.get(user.id, "TERMINAL")
            
            text = "📊 <b>Pilih Strategi Trading:</b>\n\n"
            keyboard = []
            
            for key, info in STRATEGIES.items():
                mark = "✅ " if key == selected else ""
                keyboard.append([
                    InlineKeyboardButton(
                        f"{mark}{info['icon']} {info['name']}",
                        callback_data=f"strategy_{key}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")])
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif menu == "pair":
            symbols = get_short_term_symbols()
            selected = self._user_context.get(f"selected_symbol_{user.id}", "R_100")
            
            keyboard = []
            row = []
            for symbol in symbols:
                mark = "✅ " if symbol == selected else ""
                row.append(InlineKeyboardButton(f"{mark}{symbol}", callback_data=f"symbol_{symbol}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")])
            
            await query.edit_message_text(
                "💱 <b>Pilih Pair Trading:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif menu == "autotrade":
            # Show trading setup inline instead of using FakeUpdate
            if user.id in self._trading_managers:
                tm = self._trading_managers[user.id]
                if tm.state == TradingState.RUNNING:
                    keyboard = [
                        [InlineKeyboardButton("⏹️ Stop Trading", callback_data="confirm_stop_trading")],
                        [InlineKeyboardButton("🔄 Force Restart", callback_data="force_restart_trading")],
                        [InlineKeyboardButton("🔙 Menu", callback_data="menu_main")]
                    ]
                    await query.edit_message_text(
                        "⚠️ <b>Trading sedang berjalan</b>\n\n"
                        "Pilih aksi:\n"
                        "• <b>Stop Trading</b> - Hentikan trading saat ini\n"
                        "• <b>Force Restart</b> - Stop paksa dan mulai ulang",
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return
            
            # Show trading setup
            selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
            selected_symbol = self._user_context.get(f"selected_symbol_{user.id}", "R_100")
            trade_count = self._user_context.get(f"trade_count_{user.id}", 10)
            trade_count_display = "∞ Unlimited" if trade_count == 0 else str(trade_count)
            
            strategy_info = STRATEGIES.get(selected_strategy, {})
            escaped_name = html.escape(strategy_info.get('name', selected_strategy))
            escaped_symbol = html.escape(selected_symbol)
            
            text = f"""
▶️ <b>Auto Trade Setup</b>

📊 Strategi: {strategy_info.get('icon', '')} <b>{escaped_name}</b>
💱 Symbol: {escaped_symbol}
🎯 Target Trade: {trade_count_display}

Konfigurasi trading otomatis:
"""
            
            keyboard = [
                [InlineKeyboardButton("💵 Pilih Stake", callback_data=f"change_stake_{selected_strategy}")],
                [InlineKeyboardButton("🎯 Target Trade", callback_data="menu_trade_count")],
                [InlineKeyboardButton("📊 Ubah Strategi", callback_data="menu_strategy")],
                [InlineKeyboardButton("💱 Ubah Symbol", callback_data="menu_pair")],
                [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif menu == "trade_count":
            await self._show_trade_count_selection(query, user)
        
        elif menu == "status":
            if user.id not in self._trading_managers:
                await query.edit_message_text(
                    "💤 Status: IDLE\n\nGunakan menu Auto Trade untuk memulai.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
                    ])
                )
            else:
                tm = self._trading_managers[user.id]
                status = tm.get_status()
                
                escaped_state = html.escape(str(status['state']))
                escaped_symbol = html.escape(str(status['symbol']))
                await query.edit_message_text(
                    f"📊 <b>Status Trading</b>\n\n"
                    f"🔄 State: {escaped_state}\n"
                    f"💱 Symbol: {escaped_symbol}\n"
                    f"🎯 Trades: {status['session_trades']}/{status['target_trades']}\n"
                    f"💰 Profit: ${status['session_profit']:.2f}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("⏹️ Stop Trading", callback_data="confirm_stop_trading")],
                        [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
                    ])
                )
        
        elif menu == "account":
            ws = self._ws_connections.get(user.id)
            if not ws or not ws.is_connected():
                await query.edit_message_text(
                    "❌ Tidak terhubung. Silakan login ulang.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
                    ])
                )
                return
            
            account_type = user_auth.get_account_type(user.id) or "unknown"
            balance = ws.get_balance()
            currency = ws.get_currency()
            
            escaped_currency = html.escape(currency)
            escaped_loginid = html.escape(ws.loginid or 'N/A')
            await query.edit_message_text(
                f"👤 <b>Info Akun</b>\n\n"
                f"📋 Tipe: {account_type.upper()}\n"
                f"💰 Saldo: {balance:.2f} {escaped_currency}\n"
                f"🆔 Login ID: {escaped_loginid}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Switch Account", callback_data="switch_account")],
                    [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
                ])
            )
        
        elif menu == "language":
            keyboard = []
            row = []
            
            for code, name in list(SUPPORTED_LANGUAGES.items())[:12]:
                row.append(InlineKeyboardButton(f"{name}", callback_data=f"lang_{code}"))
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")])
            
            await query.edit_message_text(
                "🌍 <b>Pilih Bahasa:</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif menu == "help":
            await query.edit_message_text(
                "📖 <b>Panduan</b>\n\n"
                "1. Login dengan /login\n"
                "2. Pilih strategi dengan /strategi\n"
                "3. Buka WebApp atau mulai /autotrade\n"
                "4. Monitor dengan /status\n\n"
                "Gunakan /help untuk panduan lengkap.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
                ])
            )
    
    async def _handle_confirm_callback(self, query: CallbackQuery, user: User, data: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle confirmation callbacks"""
        action = data.replace("confirm_", "")
        
        if action == "logout":
            if user.id in self._trading_managers:
                self._trading_managers[user.id].stop()
                del self._trading_managers[user.id]
            
            if user.id in self._ws_connections:
                self._ws_connections[user.id].disconnect()
                del self._ws_connections[user.id]
            
            # Clear session_manager data and unregister trading manager
            try:
                from web_server import session_manager, unregister_deriv_connection, unregister_trading_manager
                session_manager.clear_user_data(user.id)
                unregister_deriv_connection(user.id)
                unregister_trading_manager(user.id)
            except Exception as e:
                logger.error(f"Failed to clear session_manager: {e}")
            
            user_auth.logout(user.id)
            
            await query.edit_message_text("✅ Berhasil logout. Sampai jumpa!")
        
        elif action == "start_trading":
            # Check if stake was explicitly selected for current strategy
            selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
            stake_key = f"selected_stake_{user.id}"
            
            if stake_key not in self._user_context:
                # Stake not selected, show stake selection first
                await query.answer("Silakan pilih stake terlebih dahulu", show_alert=True)
                await self._show_stake_selection(query, user, selected_strategy)
                return
            
            await self._start_trading(query, user, context)
        
        elif action == "stop_trading":
            if user.id in self._trading_managers:
                tm = self._trading_managers[user.id]
                
                # Get stats before stopping
                status = tm.get_status()
                wins = status.get("wins", 0)
                losses = status.get("losses", 0)
                total_trades = status.get("trades", 0)
                win_rate = status.get("win_rate", 0)
                session_profit = status.get("session_profit", 0)
                balance = status.get("balance", 0)
                strategy = status.get("strategy", "N/A")
                
                tm.stop()
                del self._trading_managers[user.id]
                
                # Unregister from web_server
                try:
                    from web_server import unregister_trading_manager
                    unregister_trading_manager(user.id)
                except Exception as e:
                    logger.error(f"Failed to unregister trading manager: {e}")
                
                # Format stop message with stats
                profit_emoji = "📈" if session_profit >= 0 else "📉"
                profit_color = "+" if session_profit >= 0 else ""
                
                stop_message = f"""⏹️ <b>Trading Dihentikan</b>

📊 <b>Ringkasan Sesi:</b>
├ Strategi: {strategy}
├ Total Trade: {total_trades}
├ ✅ Win: {wins}
├ ❌ Lose: {losses}
├ 📊 Winrate: {win_rate:.1f}%
└ {profit_emoji} Profit: {profit_color}${session_profit:.2f}

💰 Balance: ${balance:.2f}"""
                
                await query.edit_message_text(
                    stop_message,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
                    ])
                )
    
    async def _handle_force_restart_trading(self, query: CallbackQuery, user: User, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle force restart trading - stops any existing trading and starts fresh"""
        try:
            # Force stop existing trading manager
            result = self.force_stop_trading(user.id)
            logger.info(f"Force restart for user {user.id}: {result}")
            
            await query.edit_message_text(
                "🔄 <b>Force Restart</b>\n\n"
                "Trading lama dihentikan paksa.\n"
                "Memulai trading baru...",
                parse_mode=ParseMode.HTML
            )
            
            # Small delay to ensure cleanup
            await asyncio.sleep(0.5)
            
            # Start new trading session
            await self._start_trading(query, user, context)
            
        except Exception as e:
            logger.error(f"Force restart failed for user {user.id}: {e}")
            await query.edit_message_text(
                f"❌ Gagal force restart: {str(e)}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Menu", callback_data="menu_main")]
                ])
            )
    
    async def _handle_switch_account(self, query: CallbackQuery, user: User) -> None:
        """Handle account switch"""
        if user.id in self._trading_managers:
            self._trading_managers[user.id].stop()
            del self._trading_managers[user.id]
        
        if user.id in self._ws_connections:
            self._ws_connections[user.id].disconnect()
            del self._ws_connections[user.id]
        
        # Clear session_manager data and unregister trading manager
        try:
            from web_server import session_manager, unregister_deriv_connection, unregister_trading_manager
            session_manager.clear_user_data(user.id)
            unregister_deriv_connection(user.id)
            unregister_trading_manager(user.id)
        except Exception as e:
            logger.error(f"Failed to clear session_manager: {e}")
        
        user_auth.logout(user.id)
        
        keyboard = [
            [
                InlineKeyboardButton("🔵 Demo", callback_data="login_demo"),
                InlineKeyboardButton("🟢 Real", callback_data="login_real")
            ]
        ]
        
        await query.edit_message_text(
            "🔐 <b>Login ke Deriv</b>\n\nPilih tipe akun:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ==================== Message Handler ====================
    
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text messages (primarily for token input)"""
        user = update.effective_user
        message = update.message
        chat = update.effective_chat
        if user is None or message is None or chat is None or message.text is None:
            return
        text = message.text.strip()
        lang = get_user_language(user.id)
        
        if user_auth.has_pending_login(user.id):
            result = user_auth.submit_token(user.id, text, lang)
            
            try:
                await message.delete()
            except:
                pass
            
            if result["success"]:
                # Try to connect to Deriv
                connected, error_msg = await self._connect_deriv(user.id)
                
                if connected:
                    ws = self._ws_connections[user.id]
                    escaped_currency = html.escape(ws.get_currency())
                    await chat.send_message(
                        f"✅ <b>Login Berhasil!</b>\n\n"
                        f"📋 Tipe: {result['account_type'].upper()}\n"
                        f"💰 Saldo: {ws.get_balance():.2f} {escaped_currency}",
                        parse_mode=ParseMode.HTML
                    )
                    
                    # Set default strategy
                    self._user_strategies[user.id] = "TERMINAL"
                    await self._notify_webapp_strategy_change(user.id, "TERMINAL")
                    
                    # Show main menu - capture local references to avoid stale references
                    local_user = user
                    local_chat_send = chat.send_message
                    
                    class FakeUpdate:
                        effective_user = local_user
                        callback_query = None
                        message = type('obj', (object,), {
                            'reply_text': local_chat_send
                        })()
                    
                    await self._show_main_menu(FakeUpdate(), context)  # type: ignore[arg-type]
                else:
                    # Show detailed error message from Deriv
                    error_text = error_msg if error_msg else "Gagal terhubung ke Deriv. Silakan coba lagi."
                    await chat.send_message(
                        f"❌ <b>Login Gagal</b>\n\n{html.escape(error_text)}",
                        parse_mode=ParseMode.HTML
                    )
            else:
                error_text = result.get('error', 'Login gagal')
                if error_text == "invalid_token_format":
                    error_text = "Format token tidak valid. Token harus 15-100 karakter alfanumerik."
                elif error_text == "login_timeout":
                    error_text = "Waktu login habis. Silakan coba lagi dengan /login"
                elif error_text == "no_pending_login":
                    error_text = "Silakan mulai login dengan /login terlebih dahulu."
                
                await chat.send_message(
                    f"❌ {error_text}"
                )
    
    # ==================== Deriv Connection ====================
    
    async def _connect_deriv(self, user_id: int, notify_callback=None) -> tuple:
        """
        Connect to Deriv WebSocket with retry mechanism and notifications
        
        Args:
            user_id: Telegram user ID
            notify_callback: Optional async callback for retry notifications
        
        Returns:
            tuple: (success: bool, error_message: Optional[str])
        """
        max_connection_retries = 3
        
        try:
            token = user_auth.get_token(user_id)
            if not token:
                return False, "Token tidak ditemukan. Silakan login ulang."
            
            # Validate token format
            if len(token) < 10:
                return False, "Format token tidak valid. Token terlalu pendek."
            
            # Close existing connection if any
            if user_id in self._ws_connections:
                try:
                    self._ws_connections[user_id].disconnect()
                except:
                    pass
            
            # Connection retry loop
            for conn_attempt in range(1, max_connection_retries + 1):
                try:
                    logger.info(f"Connection attempt {conn_attempt}/{max_connection_retries} for user {user_id}")
                    
                    # Create WebSocket connection
                    ws = DerivWebSocket()
                    
                    # Connect to WebSocket with reduced timeout
                    if not ws.connect(timeout=10):
                        logger.warning(f"WebSocket connect failed (attempt {conn_attempt})")
                        if conn_attempt < max_connection_retries:
                            wait_time = 2 ** conn_attempt
                            logger.info(f"Retrying connection in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            return False, "Gagal terhubung ke server Deriv setelah beberapa percobaan."
                    
                    logger.info(f"WebSocket connected for user {user_id}")
                    
                    # Authorize with token (has built-in retry mechanism)
                    success, error_msg = ws.authorize(token, timeout=20, max_retries=3)
                    
                    if not success:
                        logger.error(f"Failed to authorize for user {user_id}: {error_msg}")
                        ws.disconnect()
                        
                        # Check if it's a token error (no retry needed)
                        if error_msg and ("tidak valid" in error_msg.lower() or "invalid" in error_msg.lower()):
                            user_auth.clear_invalid_session(user_id)
                            return False, error_msg
                        
                        # For timeout errors, retry connection
                        if conn_attempt < max_connection_retries:
                            wait_time = 2 ** conn_attempt
                            logger.info(f"Retrying full connection in {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            user_auth.clear_invalid_session(user_id)
                            return False, error_msg
                    
                    # Store connection
                    self._ws_connections[user_id] = ws
                    
                    # Register with web server and sync to session_manager
                    try:
                        from web_server import register_deriv_connection, session_manager
                        register_deriv_connection(user_id, ws)
                        
                        # Sync Deriv token to session_manager for WebApp auto-connect
                        session_manager.set_deriv_token(user_id, token)
                        
                        # Sync account info
                        account_data = {
                            "balance": ws.get_balance() if hasattr(ws, 'get_balance') else 0,
                            "currency": ws.get_currency() if hasattr(ws, 'get_currency') else "USD",
                            "loginid": ws.loginid if hasattr(ws, 'loginid') else "",
                            "account_type": ws.account_type if hasattr(ws, 'account_type') else "demo"
                        }
                        session_manager.set_deriv_account(user_id, account_data)
                        logger.info(f"Synced Deriv token and account to session_manager for user {user_id}")
                    except Exception as sync_error:
                        logger.error(f"Failed to sync to session_manager: {sync_error}")
                    
                    logger.info(f"User {user_id} connected to Deriv successfully")
                    return True, None
                    
                except Exception as e:
                    logger.error(f"Connection attempt {conn_attempt} error: {e}")
                    if conn_attempt < max_connection_retries:
                        wait_time = 2 ** conn_attempt
                        await asyncio.sleep(wait_time)
                    else:
                        return False, f"Kesalahan koneksi setelah beberapa percobaan: {str(e)}"
            
            return False, "Gagal terhubung setelah beberapa percobaan"
            
        except Exception as e:
            logger.error(f"Error connecting to Deriv for user {user_id}: {e}")
            return False, f"Kesalahan koneksi: {str(e)}"
    
    def _get_detailed_error_message(self, error) -> str:
        """Get detailed and actionable error message"""
        error_str = str(error).lower()
        
        if "timeout" in error_str:
            return (
                "Connection timeout - kemungkinan:\n"
                "1. Koneksi internet lambat\n"
                "2. Server Deriv sedang sibuk\n"
                "3. Token tidak valid\n\n"
                "Solusi:\n"
                "- Cek koneksi internet\n"
                "- Generate token baru di Deriv\n"
                "- Coba lagi beberapa saat"
            )
        elif "invalid" in error_str or "tidak valid" in error_str:
            return "Token tidak valid. Silakan generate token baru di Deriv."
        elif "expired" in error_str or "kadaluarsa" in error_str:
            return "Token sudah kadaluarsa. Silakan generate token baru di Deriv."
        elif "permission" in error_str or "izin" in error_str:
            return "Token tidak memiliki izin yang cukup. Pastikan token memiliki izin 'trade' dan 'read'."
        elif "rate" in error_str:
            return "Terlalu banyak permintaan. Silakan tunggu beberapa menit."
        else:
            return f"Error: {str(error)}"
    
    # ==================== Trading ====================
    
    async def _start_trading(self, query, user, context):
        """Start auto trading"""
        ws = self._ws_connections.get(user.id)
        if not ws or not ws.is_connected():
            await query.edit_message_text(
                "❌ Tidak terhubung ke Deriv. Silakan login ulang.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔐 Login", callback_data="login_demo")]
                ])
            )
            return
        
        selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
        selected_symbol = self._user_context.get(f"selected_symbol_{user.id}", "R_100")
        
        # Get selected stake (required - must be explicitly selected)
        stake_key = f"selected_stake_{user.id}"
        if stake_key not in self._user_context:
            # This should not happen as we check in confirm_start_trading
            await query.answer("Silakan pilih stake terlebih dahulu", show_alert=True)
            await self._show_stake_selection(query, user, selected_strategy)
            return
        
        selected_stake = self._user_context[stake_key]
        strategy_config = get_strategy_config(selected_strategy)
        
        # Map strategy name to enum
        strategy_map = {
            "TERMINAL": StrategyType.TERMINAL,
            "TICK_PICKER": StrategyType.TICK_PICKER,
            "DIGITPAD": StrategyType.DIGITPAD,
            "AMT": StrategyType.AMT,
            "SNIPER": StrategyType.SNIPER,
            "LDP": StrategyType.LDP,
            "MULTI_INDICATOR": StrategyType.MULTI_INDICATOR
        }
        strategy_type = strategy_map.get(selected_strategy, StrategyType.MULTI_INDICATOR)
        
        # Create trading config with selected stake
        config = TradingConfig(
            symbol=selected_symbol,
            base_stake=selected_stake,
            payout_percent=85.0,
            take_profit=10.0,
            stop_loss=25.0,
            max_trades=100,
            strategy=strategy_type
        )
        
        # Force stop and cleanup any existing trading manager
        if user.id in self._trading_managers:
            old_tm = self._trading_managers[user.id]
            if old_tm.state in [TradingState.RUNNING, TradingState.PAUSED, TradingState.STOPPING]:
                logger.info(f"Force stopping existing trading manager for user {user.id} (state: {old_tm.state.value})")
                try:
                    old_tm.stop()
                except Exception as e:
                    logger.error(f"Error stopping old trading manager: {e}")
            del self._trading_managers[user.id]
            
            # Unregister old manager from web_server
            try:
                from web_server import unregister_trading_manager
                unregister_trading_manager(user.id)
            except Exception as e:
                logger.error(f"Error unregistering old trading manager: {e}")
        
        # Always create a fresh TradingManager to avoid stuck state issues
        tm = TradingManager(ws, config)
        self._trading_managers[user.id] = tm
        
        # Register with web_server for API access
        try:
            from web_server import register_trading_manager
            register_trading_manager(user.id, tm)
            logger.info(f"Registered trading manager with web_server for user {user.id}")
        except Exception as e:
            logger.error(f"Failed to register trading manager with web_server: {e}")
        
        # Setup callbacks for real-time notifications
        chat_id = query.message.chat_id
        
        # Get the running event loop for thread-safe callbacks
        loop = asyncio.get_running_loop()
        
        def on_trade_opened(trade_info):
            """Callback when trade is opened"""
            logger.info(f"Trade opened for user {user.id}: {trade_info}")
            try:
                asyncio.run_coroutine_threadsafe(
                    self._notify_trade_opened(chat_id, trade_info),
                    loop
                )
            except Exception as e:
                logger.error(f"Failed to send trade opened notification: {e}")
            
            webapp_mgr = get_webapp_manager()
            if webapp_mgr:
                try:
                    asyncio.run_coroutine_threadsafe(
                        webapp_mgr.send_personal(str(user.id), {
                            "type": "trade_opened",
                            "data": trade_info
                        }),
                        loop
                    )
                except Exception as e:
                    logger.error(f"Failed to broadcast trade opened to webapp: {e}")
        
        def on_trade_closed(trade_result):
            """Callback when trade is closed"""
            logger.info(f"Trade closed for user {user.id}: {trade_result}")
            try:
                asyncio.run_coroutine_threadsafe(
                    self._notify_trade_closed(chat_id, trade_result),
                    loop
                )
            except Exception as e:
                logger.error(f"Failed to send trade closed notification: {e}")
            
            webapp_mgr = get_webapp_manager()
            if webapp_mgr:
                try:
                    asyncio.run_coroutine_threadsafe(
                        webapp_mgr.send_personal(str(user.id), {
                            "type": "trade_closed",
                            "data": trade_result
                        }),
                        loop
                    )
                except Exception as e:
                    logger.error(f"Failed to broadcast trade closed to webapp: {e}")
        
        def on_error(error_msg):
            """Callback on error"""
            logger.error(f"Trading error for user {user.id}: {error_msg}")
            try:
                asyncio.run_coroutine_threadsafe(
                    self._notify_trading_error(chat_id, error_msg),
                    loop
                )
            except Exception as e:
                logger.error(f"Failed to send error notification: {e}")
        
        def on_progress(progress_info):
            """Callback for progress updates (warmup, etc.)"""
            try:
                msg_type = progress_info.get("type", "")
                message = progress_info.get("message", "Loading...")
                
                if msg_type in ["warmup", "warmup_complete"]:
                    if self.application is not None and self.application.bot is not None:
                        bot = self.application.bot
                        asyncio.run_coroutine_threadsafe(
                            bot.send_message(
                                chat_id,
                                message
                            ),
                            loop
                        )
                        logger.info(f"Progress notification sent to user {user.id}: {message}")
            except Exception as e:
                logger.error(f"Failed to send progress notification: {e}")
        
        tm.on_trade_opened = on_trade_opened
        tm.on_trade_closed = on_trade_closed
        tm.on_error = on_error
        tm.on_progress = on_progress
        
        # Apply trade count setting from user context BEFORE starting
        trade_count = self._user_context.get(f"trade_count_{user.id}", 10)
        is_unlimited = trade_count == 0
        tm.set_trade_count(trade_count, unlimited=is_unlimited)
        logger.info(f"Trade count set for user {user.id}: {'UNLIMITED' if is_unlimited else trade_count}")
        
        # Start trading
        started = tm.start()
        
        if not started:
            await query.edit_message_text(
                "❌ Gagal memulai trading. Pastikan koneksi Deriv aktif.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Menu", callback_data="menu_main")]
                ])
            )
            return
        
        strategy_info = STRATEGIES.get(selected_strategy, {})
        
        strategy_name = html.escape(strategy_info.get('name', selected_strategy))
        symbol_name = html.escape(selected_symbol)

        await query.edit_message_text(
            f"▶️ <b>Trading Dimulai!</b>\n\n"
            f"📊 Strategi: {strategy_info.get('icon', '')} {strategy_name}\n"
            f"💱 Symbol: {symbol_name}\n"
            f"💵 Stake: ${selected_stake:.2f}\n\n"
            f"Gunakan /status untuk melihat progress\n"
            f"Gunakan /stop untuk menghentikan",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📈 Status", callback_data="menu_status")],
                [InlineKeyboardButton("⏹️ Stop", callback_data="confirm_stop_trading")],
                [InlineKeyboardButton("🔙 Menu", callback_data="menu_main")]
            ])
        )
        
        # Start monitoring in background
        asyncio.create_task(self._monitor_trading(user.id, query.message.chat_id))
    
    async def _monitor_trading(self, user_id: int, chat_id: int):
        """Monitor trading and send notifications"""
        tm = self._trading_managers.get(user_id)
        if not tm:
            return
        
        last_trade_count = 0
        
        while tm.state == TradingState.RUNNING:
            await asyncio.sleep(5)
            
            status = tm.get_status()
            current_trades = status['session_trades']
            
            # Send notification on new trade
            if current_trades > last_trade_count:
                profit = status['session_profit']
                profit_text = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
                
                await self._send_rate_limited(
                    chat_id,
                    f"📊 Trade #{current_trades}: {profit_text}\n"
                    f"Win Rate: {status['win_rate']:.1f}%"
                )
                
                last_trade_count = current_trades
            
            # Check if completed (skip if unlimited mode)
            is_unlimited = status.get('unlimited_mode', False)
            target = status.get('target_trades', 50)
            if not is_unlimited and target > 0 and current_trades >= target:
                if self.application is not None and self.application.bot is not None:
                    bot = self.application.bot
                    await bot.send_message(
                        chat_id,
                        f"🏁 <b>Target Tercapai!</b>\n\n"
                        f"Total Trades: {current_trades}\n"
                        f"Profit: ${status['session_profit']:.2f}\n"
                        f"Win Rate: {status['win_rate']:.1f}%",
                        parse_mode=ParseMode.HTML
                    )
                tm.stop()
                break
    
    async def _send_rate_limited(self, chat_id: int, text: str, parse_mode: Optional[str] = None):
        """Send message with rate limiting"""
        now = time.time()
        last_time = self._last_message_time.get(chat_id, 0)
        
        if now - last_time < self.MESSAGE_RATE_LIMIT:
            return
        
        self._last_message_time[chat_id] = now
        
        try:
            if self.application is not None and self.application.bot is not None:
                bot = self.application.bot
                await bot.send_message(chat_id, text, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
    # ==================== Notification Methods ====================
    
    async def _notify_trade_opened(self, chat_id: int, trade_info: dict):
        """Notify user when a trade is opened"""
        try:
            contract_type = trade_info.get('contract_type', 'N/A')
            stake = trade_info.get('stake', 0)
            buy_price = trade_info.get('buy_price', stake)
            trade_num = trade_info.get('trade_number', 1)
            symbol = trade_info.get('symbol', '')
            
            text = (
                f"⏳ <b>ENTRY (Trade {trade_num})</b>\n\n"
                f"• Tipe: {contract_type}\n"
                f"• Symbol: {symbol}\n"
                f"• Stake: ${buy_price:.2f}"
            )
            
            await self._send_rate_limited(
                chat_id, text, parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Failed to notify trade opened: {e}")
    
    async def _notify_trade_closed(self, chat_id: int, trade_result: dict):
        """Notify user when a trade is closed"""
        try:
            profit = trade_result.get('profit', 0)
            balance = trade_result.get('balance', 0)
            trades = trade_result.get('trades', 0)
            next_stake = trade_result.get('next_stake', 1.0)
            stake = trade_result.get('stake', 1.0)
            
            if profit > 0:
                emoji = "✅"
                result_text = "WIN"
                profit_text = f"+${profit:.2f}"
            else:
                emoji = "❌"
                result_text = "LOSS"
                profit_text = f"-${abs(stake):.2f}"
            
            text = (
                f"{emoji} <b>{result_text} ({trades})</b>\n\n"
                f"• {'Profit' if profit > 0 else 'Loss'}: {profit_text}\n"
                f"• Saldo: ${balance:.2f}\n"
                f"• Next Stake: ${next_stake:.2f}"
            )
            
            if self.application is not None and self.application.bot is not None:
                bot = self.application.bot
                await bot.send_message(
                    chat_id, text, parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Failed to notify trade closed: {e}")
    
    async def _notify_trading_error(self, chat_id: int, error_msg: str):
        """Notify user of trading error"""
        try:
            escaped_msg = html.escape(error_msg)
            if self.application is not None and self.application.bot is not None:
                bot = self.application.bot
                await bot.send_message(
                    chat_id,
                    f"⚠️ <b>Trading Error:</b>\n\n<pre>{escaped_msg}</pre>",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logger.error(f"Failed to notify trading error: {e}")
    
    async def send_trade_notification(self, user_id: int, trade_result: dict):
        """Send trade notification to user"""
        chat_id = chat_mapping.get_chat_id(user_id)
        if not chat_id:
            return
        
        won = trade_result.get('profit', 0) > 0
        emoji = "✅" if won else "❌"
        profit = trade_result.get('profit', 0)
        
        text = f"{emoji} Trade Result: {'WIN' if won else 'LOSS'} ${abs(profit):.2f}"
        
        await self._send_rate_limited(chat_id, text)
    
    async def send_signal_notification(self, user_id: int, signal: dict):
        """Send signal notification to user"""
        chat_id = chat_mapping.get_chat_id(user_id)
        if not chat_id:
            return
        
        direction = html.escape(signal.get('direction', 'N/A'))
        confidence = signal.get('confidence', 0)
        
        if confidence >= 80:
            text = f"🎯 <b>High Confidence Signal:</b> {direction} ({confidence:.1f}%)"
            await self._send_rate_limited(chat_id, text, parse_mode=ParseMode.HTML)


# Create bot instance function
def create_bot(token: str, webapp_base_url: Optional[str] = None) -> TelegramBot:
    """Create and return a TelegramBot instance"""
    return TelegramBot(token, webapp_base_url)
