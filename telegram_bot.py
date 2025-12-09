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
from typing import Dict, Any, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
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

logger = logging.getLogger(__name__)


# Strategy configurations with WebApp routes
STRATEGIES = {
    "TERMINAL": {
        "name": "Terminal",
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
        "webapp_route": "/digitpad"
    },
    "MULTI_INDICATOR": {
        "name": "Multi-Indicator",
        "icon": "📉",
        "description": "RSI, EMA, MACD, Stochastic, ADX",
        "webapp_route": "/terminal"
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
    
    def __init__(self, token: str, webapp_base_url: str = None):
        self.token = token
        self.webapp_base_url = webapp_base_url or os.environ.get("WEBAPP_BASE_URL", "https://your-domain.com")
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
        """Start the Telegram bot"""
        self.application = Application.builder().token(self.token).build()
        self._register_handlers()
        
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        logger.info("Telegram bot started")
    
    async def stop(self):
        """Stop the Telegram bot"""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
        
        for ws in self._ws_connections.values():
            ws.disconnect()
        
        logger.info("Telegram bot stopped")
    
    def _register_handlers(self):
        """Register command and callback handlers"""
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
        
        # Callback queries
        app.add_handler(CallbackQueryHandler(self._handle_callback))
        
        # Message handler for token input
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_message
        ))
    
    def _get_webapp_url(self, user_id: int, strategy: str = None) -> str:
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
    
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        lang = detect_language(user.language_code)
        set_user_language(user.id, lang)
        chat_mapping.set_chat_id(user.id, chat_id)
        
        if user_auth.is_logged_in(user.id):
            await self._show_main_menu(update, context)
        else:
            await self._show_welcome(update, context)
    
    async def _show_welcome(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show welcome screen with login options"""
        user = update.effective_user
        lang = get_user_language(user.id)
        
        text = f"""
🤖 *Deriv Auto Trading Bot*

Selamat datang, {user.first_name}!

Bot ini membantu Anda trading di Deriv dengan berbagai strategi otomatis:

⚡ *Terminal* - Smart Analysis 80%
📈 *Tick Picker* - Pattern Analysis
🔢 *DigitPad* - Digit Frequency
📊 *AMT* - Accumulator
🎯 *Sniper* - High Probability

Silakan login untuk memulai:
"""
        
        keyboard = [
            [
                InlineKeyboardButton("🔵 Demo Account", callback_data="login_demo"),
                InlineKeyboardButton("🟢 Real Account", callback_data="login_real")
            ],
            [InlineKeyboardButton("📖 Panduan", callback_data="menu_help")]
        ]
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu after login"""
        user = update.effective_user
        lang = get_user_language(user.id)
        
        ws = self._ws_connections.get(user.id)
        balance = ws.get_balance() if ws and ws.is_connected() else 0
        currency = ws.get_currency() if ws and ws.is_connected() else "USD"
        account_type = user_auth.get_account_type(user.id) or "demo"
        
        selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
        strategy_info = STRATEGIES.get(selected_strategy, {})
        
        text = f"""
🏠 *Menu Utama*

👤 Account: {account_type.upper()}
💰 Balance: {balance:.2f} {currency}
📊 Strategy: {strategy_info.get('icon', '')} {strategy_info.get('name', selected_strategy)}

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
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    async def _cmd_strategy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /strategi command - Show strategy selection"""
        user = update.effective_user
        selected = self._user_strategies.get(user.id, "TERMINAL")
        
        text = f"""
📊 *Pilih Strategi Trading*

Strategi saat ini: {STRATEGIES.get(selected, {}).get('icon', '')} {STRATEGIES.get(selected, {}).get('name', selected)}

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
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_webapp(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /webapp command - Open WebApp"""
        user = update.effective_user
        
        if not user_auth.is_logged_in(user.id):
            await update.message.reply_text("❌ Silakan login terlebih dahulu dengan /login")
            return
        
        selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
        strategy_info = STRATEGIES.get(selected_strategy, {})
        webapp_url = self._get_webapp_url(user.id, selected_strategy)
        
        text = f"""
🌐 *WebApp {strategy_info.get('name', '')}*

{strategy_info.get('icon', '')} {strategy_info.get('description', '')}

Klik tombol di bawah untuk membuka WebApp:
"""
        
        keyboard = [[
            InlineKeyboardButton(
                f"🚀 Buka {strategy_info.get('name', 'WebApp')}",
                web_app=WebAppInfo(url=webapp_url)
            )
        ]]
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /login command"""
        user = update.effective_user
        lang = get_user_language(user.id)
        
        if user_auth.is_logged_in(user.id):
            await update.message.reply_text(
                "✅ Anda sudah login. Gunakan /logout untuk keluar terlebih dahulu."
            )
            return
        
        keyboard = [
            [
                InlineKeyboardButton("🔵 Demo", callback_data="login_demo"),
                InlineKeyboardButton("🟢 Real", callback_data="login_real")
            ]
        ]
        
        await update.message.reply_text(
            "🔐 *Login ke Deriv*\n\nPilih tipe akun:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_logout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /logout command"""
        user = update.effective_user
        
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
        
        await update.message.reply_text("✅ Berhasil logout. Sampai jumpa!")
    
    async def _cmd_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /akun command"""
        user = update.effective_user
        
        if not user_auth.is_logged_in(user.id):
            await update.message.reply_text("❌ Silakan login terlebih dahulu dengan /login")
            return
        
        ws = self._ws_connections.get(user.id)
        if not ws or not ws.is_connected():
            await update.message.reply_text("❌ Tidak terhubung ke Deriv. Silakan login ulang.")
            return
        
        account_type = user_auth.get_account_type(user.id)
        balance = ws.get_balance()
        currency = ws.get_currency()
        
        text = f"""
👤 *Info Akun*

📋 Tipe: {account_type.upper()}
💰 Saldo: {balance:.2f} {currency}
🆔 Login ID: {ws.loginid or 'N/A'}
"""
        
        keyboard = [
            [InlineKeyboardButton("🔄 Switch Account", callback_data="switch_account")],
            [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
        ]
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_autotrade(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /autotrade command"""
        user = update.effective_user
        
        if not user_auth.is_logged_in(user.id):
            await update.message.reply_text("❌ Silakan login terlebih dahulu dengan /login")
            return
        
        if user.id in self._trading_managers:
            tm = self._trading_managers[user.id]
            if tm.state == TradingState.RUNNING:
                await update.message.reply_text(
                    "⚠️ Trading sudah berjalan. Gunakan /stop untuk menghentikan."
                )
                return
        
        await self._show_trading_setup(update, context)
    
    async def _show_trading_setup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show trading setup menu"""
        user = update.effective_user
        
        selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
        selected_symbol = self._user_context.get(f"selected_symbol_{user.id}", "R_100")
        
        strategy_info = STRATEGIES.get(selected_strategy, {})
        
        strategy_name = strategy_info.get('name', selected_strategy)
        strategy_icon = strategy_info.get('icon', '')
        
        text = f"""⚙️ <b>Pengaturan Auto Trade</b>

📊 Strategi: {strategy_icon} {strategy_name}
💱 Pair: {selected_symbol}
💵 Stake: $1.00 (default)
🎯 Target: 10 trades

Klik tombol di bawah untuk memulai:"""
        
        keyboard = [
            [InlineKeyboardButton("📊 Ubah Strategi", callback_data="menu_strategy")],
            [InlineKeyboardButton("💱 Ubah Pair", callback_data="menu_pair")],
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
    
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop command"""
        user = update.effective_user
        
        if user.id not in self._trading_managers:
            await update.message.reply_text("❌ Tidak ada trading yang berjalan.")
            return
        
        tm = self._trading_managers[user.id]
        tm.stop()
        
        await update.message.reply_text("⏹️ Trading dihentikan.")
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user = update.effective_user
        
        if not user_auth.is_logged_in(user.id):
            await update.message.reply_text("❌ Silakan login terlebih dahulu.")
            return
        
        if user.id not in self._trading_managers:
            selected_strategy = self._user_strategies.get(user.id, "TERMINAL")
            strategy_info = STRATEGIES.get(selected_strategy, {})
            
            await update.message.reply_text(
                f"💤 Status: IDLE\n📊 Strategi: {strategy_info.get('icon', '')} {strategy_info.get('name', '')}\n\nGunakan /autotrade untuk memulai."
            )
            return
        
        tm = self._trading_managers[user.id]
        status = tm.get_status()
        
        text = f"""
📊 *Status Trading*

🔄 State: {status['state']}
💱 Symbol: {status['symbol']}
📈 Strategi: {status['strategy']}
🎯 Trades: {status['session_trades']}/{status['target_trades']}
💰 Profit: ${status['session_profit']:.2f}
📉 Win Rate: {status['win_rate']:.1f}%
"""
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        text = """
📖 *Panduan Deriv Auto Trading Bot*

*Perintah:*
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

*Strategi Tersedia:*
⚡ Terminal - Smart Analysis 80%
📈 Tick Picker - Pattern Analysis
🔢 DigitPad - Digit Frequency
📊 AMT - Accumulator
🎯 Sniper - High Probability

*Tips:*
• Gunakan Demo account untuk testing
• Pilih strategi sesuai gaya trading
• Monitor win rate Anda
• Gunakan WebApp untuk kontrol lebih
"""
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    async def _cmd_pair(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pair command"""
        symbols = get_short_term_symbols()
        selected = self._user_context.get(f"selected_symbol_{update.effective_user.id}", "R_100")
        
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
        
        await update.message.reply_text(
            "💱 *Pilih Pair Trading:*\n\n" + get_symbol_list_text(),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _cmd_language(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /language command"""
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
        
        await update.message.reply_text(
            "🌍 *Pilih Bahasa / Select Language:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ==================== Callback Handlers ====================
    
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        data = query.data
        
        if data.startswith("login_"):
            await self._handle_login_callback(query, user, data)
        elif data.startswith("strategy_"):
            await self._handle_strategy_callback(query, user, data)
        elif data.startswith("symbol_"):
            await self._handle_symbol_callback(query, user, data)
        elif data.startswith("lang_"):
            await self._handle_language_callback(query, user, data)
        elif data.startswith("menu_"):
            await self._handle_menu_callback(query, user, data, context)
        elif data.startswith("confirm_"):
            await self._handle_confirm_callback(query, user, data, context)
        elif data == "switch_account":
            await self._handle_switch_account(query, user)
    
    async def _handle_login_callback(self, query, user, data: str):
        """Handle login callbacks"""
        account_type = data.replace("login_", "")
        
        result = user_auth.start_login(user.id, account_type)
        
        if result["success"]:
            await query.edit_message_text(
                f"🔐 *Login {account_type.upper()}*\n\n"
                "Silakan kirim API Token Deriv Anda.\n\n"
                "💡 Dapatkan token di: https://app.deriv.com/account/api-token\n\n"
                "⚠️ Pesan ini akan dihapus setelah token diterima.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            if result.get("error") == "locked_out":
                await query.edit_message_text(
                    f"⚠️ Akun terkunci. Coba lagi dalam {result['remaining_seconds']} detik."
                )
    
    async def _handle_strategy_callback(self, query, user, data: str):
        """Handle strategy selection"""
        strategy = data.replace("strategy_", "")
        
        if strategy not in STRATEGIES:
            await query.answer("Strategy tidak valid", show_alert=True)
            return
        
        self._user_strategies[user.id] = strategy
        
        # Notify webapp
        await self._notify_webapp_strategy_change(user.id, strategy)
        
        strategy_info = STRATEGIES[strategy]
        webapp_url = self._get_webapp_url(user.id, strategy)
        
        text = f"""
✅ *Strategi Dipilih*

{strategy_info['icon']} *{strategy_info['name']}*
{strategy_info['description']}

Klik tombol di bawah untuk membuka WebApp atau mulai trading:
"""
        
        keyboard = [
            [InlineKeyboardButton(
                f"🌐 Buka {strategy_info['name']}",
                web_app=WebAppInfo(url=webapp_url)
            )],
            [InlineKeyboardButton("▶️ Auto Trade", callback_data="menu_autotrade")],
            [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
        ]
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def _handle_symbol_callback(self, query, user, data: str):
        """Handle symbol selection"""
        symbol = data.replace("symbol_", "")
        self._user_context[f"selected_symbol_{user.id}"] = symbol
        
        config = get_symbol_config(symbol)
        
        await query.edit_message_text(
            f"✅ *Pair Dipilih: {symbol}*\n{config.name if config else ''}\n\n"
            "Gunakan /autotrade untuk mulai trading.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
            ])
        )
    
    async def _handle_language_callback(self, query, user, data: str):
        """Handle language selection"""
        lang = data.replace("lang_", "")
        set_user_language(user.id, lang)
        
        await query.edit_message_text(
            f"✅ Bahasa diubah ke {SUPPORTED_LANGUAGES.get(lang, lang)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
            ])
        )
    
    async def _handle_menu_callback(self, query, user, data: str, context):
        """Handle menu navigation"""
        menu = data.replace("menu_", "")
        
        if menu == "main":
            # Create a fake update object for _show_main_menu
            class FakeUpdate:
                callback_query = query
                effective_user = user
                message = None
            
            await self._show_main_menu(FakeUpdate(), context)
        
        elif menu == "strategy":
            selected = self._user_strategies.get(user.id, "TERMINAL")
            
            text = "📊 *Pilih Strategi Trading:*\n\n"
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
                parse_mode=ParseMode.MARKDOWN,
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
                "💱 *Pilih Pair Trading:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif menu == "autotrade":
            class FakeUpdate:
                callback_query = query
                effective_user = user
                message = None
            
            await self._show_trading_setup(FakeUpdate(), context)
        
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
                
                await query.edit_message_text(
                    f"📊 *Status Trading*\n\n"
                    f"🔄 State: {status['state']}\n"
                    f"💱 Symbol: {status['symbol']}\n"
                    f"🎯 Trades: {status['session_trades']}/{status['target_trades']}\n"
                    f"💰 Profit: ${status['session_profit']:.2f}",
                    parse_mode=ParseMode.MARKDOWN,
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
            
            account_type = user_auth.get_account_type(user.id)
            balance = ws.get_balance()
            currency = ws.get_currency()
            
            await query.edit_message_text(
                f"👤 *Info Akun*\n\n"
                f"📋 Tipe: {account_type.upper()}\n"
                f"💰 Saldo: {balance:.2f} {currency}\n"
                f"🆔 Login ID: {ws.loginid or 'N/A'}",
                parse_mode=ParseMode.MARKDOWN,
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
                "🌍 *Pilih Bahasa:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        elif menu == "help":
            await query.edit_message_text(
                "📖 *Panduan*\n\n"
                "1. Login dengan /login\n"
                "2. Pilih strategi dengan /strategi\n"
                "3. Buka WebApp atau mulai /autotrade\n"
                "4. Monitor dengan /status\n\n"
                "Gunakan /help untuk panduan lengkap.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Kembali", callback_data="menu_main")]
                ])
            )
    
    async def _handle_confirm_callback(self, query, user, data: str, context):
        """Handle confirmation callbacks"""
        action = data.replace("confirm_", "")
        
        if action == "logout":
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
                logger.error(f"Failed to clear session_manager: {e}")
            
            user_auth.logout(user.id)
            
            await query.edit_message_text("✅ Berhasil logout. Sampai jumpa!")
        
        elif action == "start_trading":
            await self._start_trading(query, user, context)
        
        elif action == "stop_trading":
            if user.id in self._trading_managers:
                self._trading_managers[user.id].stop()
                await query.edit_message_text(
                    "⏹️ Trading dihentikan.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_main")]
                    ])
                )
    
    async def _handle_switch_account(self, query, user):
        """Handle account switch"""
        if user.id in self._trading_managers:
            self._trading_managers[user.id].stop()
        
        if user.id in self._ws_connections:
            self._ws_connections[user.id].disconnect()
            del self._ws_connections[user.id]
        
        # Clear session_manager data
        try:
            from web_server import session_manager, unregister_deriv_connection
            session_manager.clear_user_data(user.id)
            unregister_deriv_connection(user.id)
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
            "🔐 *Login ke Deriv*\n\nPilih tipe akun:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ==================== Message Handler ====================
    
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages (primarily for token input)"""
        user = update.effective_user
        text = update.message.text.strip()
        lang = get_user_language(user.id)
        
        if user_auth.has_pending_login(user.id):
            result = user_auth.submit_token(user.id, text, lang)
            
            try:
                await update.message.delete()
            except:
                pass
            
            if result["success"]:
                connected = await self._connect_deriv(user.id)
                
                if connected:
                    ws = self._ws_connections[user.id]
                    await update.effective_chat.send_message(
                        f"✅ *Login Berhasil!*\n\n"
                        f"📋 Tipe: {result['account_type'].upper()}\n"
                        f"💰 Saldo: {ws.get_balance():.2f} {ws.get_currency()}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    # Set default strategy
                    self._user_strategies[user.id] = "TERMINAL"
                    await self._notify_webapp_strategy_change(user.id, "TERMINAL")
                    
                    # Show main menu
                    class FakeUpdate:
                        effective_user = user
                        message = type('obj', (object,), {
                            'reply_text': update.effective_chat.send_message
                        })()
                    
                    await self._show_main_menu(FakeUpdate(), context)
                else:
                    await update.effective_chat.send_message(
                        "❌ Gagal terhubung ke Deriv. Token mungkin tidak valid."
                    )
            else:
                await update.effective_chat.send_message(
                    f"❌ {result.get('error', 'Login gagal')}"
                )
    
    # ==================== Deriv Connection ====================
    
    async def _connect_deriv(self, user_id: int) -> bool:
        """Connect to Deriv WebSocket"""
        try:
            token = user_auth.get_token(user_id)
            if not token:
                return False
            
            # Create WebSocket connection
            ws = DerivWebSocket()
            
            # Connect and authorize
            if not ws.connect():
                logger.error(f"Failed to connect WebSocket for user {user_id}")
                return False
            
            if not ws.authorize(token):
                logger.error(f"Failed to authorize for user {user_id}")
                ws.disconnect()
                return False
            
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
            
            logger.info(f"User {user_id} connected to Deriv")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting to Deriv for user {user_id}: {e}")
            return False
    
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
        
        # Create trading config
        config = TradingConfig(
            symbol=selected_symbol,
            base_stake=1.0,
            payout_percent=85.0,
            take_profit=10.0,
            stop_loss=25.0,
            max_trades=100,
            strategy=StrategyType.MULTI_INDICATOR
        )
        
        # Map strategy name to enum
        strategy_map = {
            "TERMINAL": StrategyType.MULTI_INDICATOR,
            "TICK_PICKER": StrategyType.TICK_ANALYZER,
            "DIGITPAD": StrategyType.LDP,
            "AMT": StrategyType.MULTI_INDICATOR,
            "SNIPER": StrategyType.MULTI_INDICATOR,
            "LDP": StrategyType.LDP,
            "MULTI_INDICATOR": StrategyType.MULTI_INDICATOR
        }
        config.strategy = strategy_map.get(selected_strategy, StrategyType.MULTI_INDICATOR)
        
        # Create or get trading manager
        if user.id not in self._trading_managers:
            tm = TradingManager(ws, config)
            self._trading_managers[user.id] = tm
        else:
            tm = self._trading_managers[user.id]
            tm.update_config(config)
        
        # Start trading
        tm.start()
        
        strategy_info = STRATEGIES.get(selected_strategy, {})
        
        await query.edit_message_text(
            f"▶️ *Trading Dimulai!*\n\n"
            f"📊 Strategi: {strategy_info.get('icon', '')} {strategy_info.get('name', selected_strategy)}\n"
            f"💱 Symbol: {selected_symbol}\n"
            f"💵 Stake: $1.00\n\n"
            f"Gunakan /status untuk melihat progress\n"
            f"Gunakan /stop untuk menghentikan",
            parse_mode=ParseMode.MARKDOWN,
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
            
            # Check if completed
            if current_trades >= status['target_trades']:
                await self.application.bot.send_message(
                    chat_id,
                    f"🏁 *Target Tercapai!*\n\n"
                    f"Total Trades: {current_trades}\n"
                    f"Profit: ${status['session_profit']:.2f}\n"
                    f"Win Rate: {status['win_rate']:.1f}%",
                    parse_mode=ParseMode.MARKDOWN
                )
                tm.stop()
                break
    
    async def _send_rate_limited(self, chat_id: int, text: str):
        """Send message with rate limiting"""
        now = time.time()
        last_time = self._last_message_time.get(chat_id, 0)
        
        if now - last_time < self.MESSAGE_RATE_LIMIT:
            return
        
        self._last_message_time[chat_id] = now
        
        try:
            await self.application.bot.send_message(chat_id, text)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
    # ==================== Notification Methods ====================
    
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
        
        direction = signal.get('direction', 'N/A')
        confidence = signal.get('confidence', 0)
        
        if confidence >= 80:
            text = f"🎯 High Confidence Signal: {direction} ({confidence}%)"
            await self._send_rate_limited(chat_id, text)


# Create bot instance function
def create_bot(token: str, webapp_base_url: str = None) -> TelegramBot:
    """Create and return a TelegramBot instance"""
    return TelegramBot(token, webapp_base_url)
