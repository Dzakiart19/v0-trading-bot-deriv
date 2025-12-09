"""
Internationalization - Multi-language support for the bot
"""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# User language preferences storage
_user_languages: Dict[int, str] = {}

# Supported languages
SUPPORTED_LANGUAGES = {
    "id": "Indonesian",
    "en": "English",
    "hi": "Hindi",
    "ar": "Arabic",
    "es": "Spanish",
    "pt": "Portuguese",
    "ru": "Russian",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "vi": "Vietnamese",
    "th": "Thai",
    "ms": "Malay",
    "tr": "Turkish",
    "de": "German",
    "fr": "French",
    "it": "Italian",
    "nl": "Dutch",
    "pl": "Polish",
    "uk": "Ukrainian",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "ur": "Urdu",
    "fa": "Persian",
    "fil": "Filipino"
}

# Message catalog
MESSAGES: Dict[str, Dict[str, str]] = {
    # Welcome messages
    "welcome": {
        "id": "Selamat datang di Deriv Auto Trading Bot! 🤖\n\nBot ini akan membantu Anda trading secara otomatis di platform Deriv.",
        "en": "Welcome to Deriv Auto Trading Bot! 🤖\n\nThis bot will help you trade automatically on the Deriv platform.",
        "hi": "Deriv Auto Trading Bot में आपका स्वागत है! 🤖\n\nयह बॉट आपको Deriv प्लेटफॉर्म पर स्वचालित रूप से व्यापार करने में मदद करेगा।",
        "ar": "مرحبًا بك في Deriv Auto Trading Bot! 🤖\n\nسيساعدك هذا البوت على التداول تلقائيًا على منصة Deriv.",
        "es": "¡Bienvenido a Deriv Auto Trading Bot! 🤖\n\nEste bot te ayudará a operar automáticamente en la plataforma Deriv.",
        "pt": "Bem-vindo ao Deriv Auto Trading Bot! 🤖\n\nEste bot irá ajudá-lo a negociar automaticamente na plataforma Deriv.",
        "ru": "Добро пожаловать в Deriv Auto Trading Bot! 🤖\n\nЭтот бот поможет вам автоматически торговать на платформе Deriv.",
        "zh": "欢迎使用 Deriv 自动交易机器人！🤖\n\n此机器人将帮助您在 Deriv 平台上自动交易。",
        "ja": "Deriv Auto Trading Botへようこそ！🤖\n\nこのボットは、Derivプラットフォームでの自動取引をサポートします。",
        "ko": "Deriv Auto Trading Bot에 오신 것을 환영합니다! 🤖\n\n이 봇은 Deriv 플랫폼에서 자동으로 거래하는 데 도움을 줄 것입니다.",
    },
    
    # Login messages
    "login_prompt": {
        "id": "Silakan pilih jenis akun:",
        "en": "Please select account type:",
        "hi": "कृपया खाता प्रकार चुनें:",
        "ar": "يرجى اختيار نوع الحساب:",
        "es": "Por favor seleccione el tipo de cuenta:",
        "pt": "Por favor, selecione o tipo de conta:",
        "ru": "Пожалуйста, выберите тип аккаунта:",
        "zh": "请选择账户类型：",
        "ja": "アカウントタイプを選択してください：",
        "ko": "계정 유형을 선택하세요:",
    },
    
    "enter_token": {
        "id": "Silakan masukkan API Token Deriv Anda:",
        "en": "Please enter your Deriv API Token:",
        "hi": "कृपया अपना Deriv API टोकन दर्ज करें:",
        "ar": "يرجى إدخال رمز API الخاص بـ Deriv:",
        "es": "Por favor ingrese su Token API de Deriv:",
        "pt": "Por favor, insira seu Token API Deriv:",
        "ru": "Пожалуйста, введите ваш API токен Deriv:",
        "zh": "请输入您的 Deriv API 令牌：",
        "ja": "Deriv APIトークンを入力してください：",
        "ko": "Deriv API 토큰을 입력하세요:",
    },
    
    "login_success": {
        "id": "✅ Login berhasil!\n\nAkun: {account_type}\nSaldo: {balance} {currency}",
        "en": "✅ Login successful!\n\nAccount: {account_type}\nBalance: {balance} {currency}",
        "hi": "✅ लॉगिन सफल!\n\nखाता: {account_type}\nशेष: {balance} {currency}",
        "ar": "✅ تم تسجيل الدخول بنجاح!\n\nالحساب: {account_type}\nالرصيد: {balance} {currency}",
        "es": "✅ ¡Inicio de sesión exitoso!\n\nCuenta: {account_type}\nSaldo: {balance} {currency}",
        "pt": "✅ Login bem-sucedido!\n\nConta: {account_type}\nSaldo: {balance} {currency}",
        "ru": "✅ Вход выполнен успешно!\n\nАккаунт: {account_type}\nБаланс: {balance} {currency}",
        "zh": "✅ 登录成功！\n\n账户：{account_type}\n余额：{balance} {currency}",
        "ja": "✅ ログイン成功！\n\nアカウント：{account_type}\n残高：{balance} {currency}",
        "ko": "✅ 로그인 성공!\n\n계정: {account_type}\n잔액: {balance} {currency}",
    },
    
    "login_failed": {
        "id": "❌ Login gagal: {error}",
        "en": "❌ Login failed: {error}",
        "hi": "❌ लॉगिन विफल: {error}",
        "ar": "❌ فشل تسجيل الدخول: {error}",
        "es": "❌ Error de inicio de sesión: {error}",
        "pt": "❌ Falha no login: {error}",
        "ru": "❌ Ошибка входа: {error}",
        "zh": "❌ 登录失败：{error}",
        "ja": "❌ ログイン失敗：{error}",
        "ko": "❌ 로그인 실패: {error}",
    },
    
    "logout_success": {
        "id": "✅ Anda telah logout.",
        "en": "✅ You have been logged out.",
        "hi": "✅ आप लॉग आउट हो गए हैं।",
        "ar": "✅ تم تسجيل خروجك.",
        "es": "✅ Has cerrado sesión.",
        "pt": "✅ Você foi desconectado.",
        "ru": "✅ Вы вышли из системы.",
        "zh": "✅ 您已退出登录。",
        "ja": "✅ ログアウトしました。",
        "ko": "✅ 로그아웃되었습니다.",
    },
    
    # Trading messages
    "trade_opened": {
        "id": "📈 Trade Dibuka\n\nSymbol: {symbol}\nArah: {direction}\nStake: ${stake}\nPayout: ${payout}\nLevel Martingale: {level}",
        "en": "📈 Trade Opened\n\nSymbol: {symbol}\nDirection: {direction}\nStake: ${stake}\nPayout: ${payout}\nMartingale Level: {level}",
        "hi": "📈 ट्रेड खोला गया\n\nसिंबल: {symbol}\nदिशा: {direction}\nस्टेक: ${stake}\nपेआउट: ${payout}\nमार्टिंगेल स्तर: {level}",
        "ar": "📈 تم فتح الصفقة\n\nالرمز: {symbol}\nالاتجاه: {direction}\nالرهان: ${stake}\nالعائد: ${payout}\nمستوى مارتينجال: {level}",
        "es": "📈 Operación Abierta\n\nSímbolo: {symbol}\nDirección: {direction}\nApuesta: ${stake}\nPago: ${payout}\nNivel Martingale: {level}",
        "pt": "📈 Operação Aberta\n\nSímbolo: {symbol}\nDireção: {direction}\nAposta: ${stake}\nPagamento: ${payout}\nNível Martingale: {level}",
        "ru": "📈 Сделка открыта\n\nСимвол: {symbol}\nНаправление: {direction}\nСтавка: ${stake}\nВыплата: ${payout}\nУровень Мартингейла: {level}",
        "zh": "📈 交易已开启\n\n品种：{symbol}\n方向：{direction}\n投注：${stake}\n赔付：${payout}\n马丁格尔级别：{level}",
        "ja": "📈 取引開始\n\nシンボル：{symbol}\n方向：{direction}\nステーク：${stake}\nペイアウト：${payout}\nマーチンゲールレベル：{level}",
        "ko": "📈 거래 시작\n\n심볼: {symbol}\n방향: {direction}\n스테이크: ${stake}\n페이아웃: ${payout}\n마틴게일 레벨: {level}",
    },
    
    "trade_closed_win": {
        "id": "✅ WIN!\n\nProfit: +${profit}\nSaldo: ${balance}\nWin Rate: {win_rate}%",
        "en": "✅ WIN!\n\nProfit: +${profit}\nBalance: ${balance}\nWin Rate: {win_rate}%",
        "hi": "✅ जीत!\n\nलाभ: +${profit}\nशेष: ${balance}\nजीत दर: {win_rate}%",
        "ar": "✅ فوز!\n\nالربح: +${profit}\nالرصيد: ${balance}\nنسبة الفوز: {win_rate}%",
        "es": "✅ ¡GANASTE!\n\nGanancia: +${profit}\nSaldo: ${balance}\nTasa de Ganancia: {win_rate}%",
        "pt": "✅ VITÓRIA!\n\nLucro: +${profit}\nSaldo: ${balance}\nTaxa de Vitória: {win_rate}%",
        "ru": "✅ ВЫИГРЫШ!\n\nПрибыль: +${profit}\nБаланс: ${balance}\nПроцент побед: {win_rate}%",
        "zh": "✅ 赢了！\n\n利润：+${profit}\n余额：${balance}\n胜率：{win_rate}%",
        "ja": "✅ 勝利！\n\n利益：+${profit}\n残高：${balance}\n勝率：{win_rate}%",
        "ko": "✅ 승리!\n\n이익: +${profit}\n잔액: ${balance}\n승률: {win_rate}%",
    },
    
    "trade_closed_loss": {
        "id": "❌ LOSS\n\nRugi: -${loss}\nSaldo: ${balance}\nWin Rate: {win_rate}%",
        "en": "❌ LOSS\n\nLoss: -${loss}\nBalance: ${balance}\nWin Rate: {win_rate}%",
        "hi": "❌ हार\n\nनुकसान: -${loss}\nशेष: ${balance}\nजीत दर: {win_rate}%",
        "ar": "❌ خسارة\n\nالخسارة: -${loss}\nالرصيد: ${balance}\nنسبة الفوز: {win_rate}%",
        "es": "❌ PÉRDIDA\n\nPérdida: -${loss}\nSaldo: ${balance}\nTasa de Ganancia: {win_rate}%",
        "pt": "❌ PERDA\n\nPerda: -${loss}\nSaldo: ${balance}\nTaxa de Vitória: {win_rate}%",
        "ru": "❌ ПРОИГРЫШ\n\nУбыток: -${loss}\nБаланс: ${balance}\nПроцент побед: {win_rate}%",
        "zh": "❌ 输了\n\n亏损：-${loss}\n余额：${balance}\n胜率：{win_rate}%",
        "ja": "❌ 負け\n\n損失：-${loss}\n残高：${balance}\n勝率：{win_rate}%",
        "ko": "❌ 패배\n\n손실: -${loss}\n잔액: ${balance}\n승률: {win_rate}%",
    },
    
    "session_complete": {
        "id": "🏁 Sesi Trading Selesai!\n\nTotal Trade: {trades}\nMenang: {wins}\nKalah: {losses}\nWin Rate: {win_rate}%\nTotal Profit: ${profit}\nSaldo Akhir: ${balance}",
        "en": "🏁 Trading Session Complete!\n\nTotal Trades: {trades}\nWins: {wins}\nLosses: {losses}\nWin Rate: {win_rate}%\nTotal Profit: ${profit}\nFinal Balance: ${balance}",
        "hi": "🏁 ट्रेडिंग सत्र पूर्ण!\n\nकुल ट्रेड: {trades}\nजीत: {wins}\nहार: {losses}\nजीत दर: {win_rate}%\nकुल लाभ: ${profit}\nअंतिम शेष: ${balance}",
        "ar": "🏁 اكتملت جلسة التداول!\n\nإجمالي الصفقات: {trades}\nالانتصارات: {wins}\nالخسائر: {losses}\nنسبة الفوز: {win_rate}%\nإجمالي الربح: ${profit}\nالرصيد النهائي: ${balance}",
        "es": "🏁 ¡Sesión de Trading Completa!\n\nTotal de Operaciones: {trades}\nGanancias: {wins}\nPérdidas: {losses}\nTasa de Ganancia: {win_rate}%\nGanancia Total: ${profit}\nSaldo Final: ${balance}",
        "pt": "🏁 Sessão de Trading Completa!\n\nTotal de Operações: {trades}\nVitórias: {wins}\nDerrotas: {losses}\nTaxa de Vitória: {win_rate}%\nLucro Total: ${profit}\nSaldo Final: ${balance}",
        "ru": "🏁 Торговая сессия завершена!\n\nВсего сделок: {trades}\nПобед: {wins}\nПроигрышей: {losses}\nПроцент побед: {win_rate}%\nОбщая прибыль: ${profit}\nИтоговый баланс: ${balance}",
        "zh": "🏁 交易会话完成！\n\n总交易：{trades}\n赢：{wins}\n输：{losses}\n胜率：{win_rate}%\n总利润：${profit}\n最终余额：${balance}",
        "ja": "🏁 取引セッション完了！\n\n総取引数：{trades}\n勝利：{wins}\n敗北：{losses}\n勝率：{win_rate}%\n総利益：${profit}\n最終残高：${balance}",
        "ko": "🏁 거래 세션 완료!\n\n총 거래: {trades}\n승리: {wins}\n패배: {losses}\n승률: {win_rate}%\n총 이익: ${profit}\n최종 잔액: ${balance}",
    },
    
    # Status messages
    "status_idle": {
        "id": "⏸️ Bot dalam keadaan idle.",
        "en": "⏸️ Bot is idle.",
        "hi": "⏸️ बॉट निष्क्रिय है।",
        "ar": "⏸️ البوت خامل.",
        "es": "⏸️ Bot está inactivo.",
        "pt": "⏸️ Bot está inativo.",
        "ru": "⏸️ Бот бездействует.",
        "zh": "⏸️ 机器人处于空闲状态。",
        "ja": "⏸️ ボットはアイドル状態です。",
        "ko": "⏸️ 봇이 대기 중입니다.",
    },
    
    "status_running": {
        "id": "🟢 Trading Aktif\n\nSymbol: {symbol}\nStrategy: {strategy}\nTrades: {trades}/{target}\nProfit: ${profit}\nWin Rate: {win_rate}%",
        "en": "🟢 Trading Active\n\nSymbol: {symbol}\nStrategy: {strategy}\nTrades: {trades}/{target}\nProfit: ${profit}\nWin Rate: {win_rate}%",
        "hi": "🟢 ट्रेडिंग सक्रिय\n\nसिंबल: {symbol}\nस्ट्रैटेजी: {strategy}\nट्रेड: {trades}/{target}\nलाभ: ${profit}\nजीत दर: {win_rate}%",
        "ar": "🟢 التداول نشط\n\nالرمز: {symbol}\nالاستراتيجية: {strategy}\nالصفقات: {trades}/{target}\nالربح: ${profit}\nنسبة الفوز: {win_rate}%",
        "es": "🟢 Trading Activo\n\nSímbolo: {symbol}\nEstrategia: {strategy}\nOperaciones: {trades}/{target}\nGanancia: ${profit}\nTasa de Ganancia: {win_rate}%",
        "pt": "🟢 Trading Ativo\n\nSímbolo: {symbol}\nEstratégia: {strategy}\nOperações: {trades}/{target}\nLucro: ${profit}\nTaxa de Vitória: {win_rate}%",
        "ru": "🟢 Торговля активна\n\nСимвол: {symbol}\nСтратегия: {strategy}\nСделки: {trades}/{target}\nПрибыль: ${profit}\nПроцент побед: {win_rate}%",
        "zh": "🟢 交易中\n\n品种：{symbol}\n策略：{strategy}\n交易：{trades}/{target}\n利润：${profit}\n胜率：{win_rate}%",
        "ja": "🟢 取引中\n\nシンボル：{symbol}\n戦略：{strategy}\n取引：{trades}/{target}\n利益：${profit}\n勝率：{win_rate}%",
        "ko": "🟢 거래 중\n\n심볼: {symbol}\n전략: {strategy}\n거래: {trades}/{target}\n이익: ${profit}\n승률: {win_rate}%",
    },
    
    # Button labels
    "btn_demo": {
        "id": "Demo Account",
        "en": "Demo Account",
        "hi": "डेमो खाता",
        "ar": "حساب تجريبي",
        "es": "Cuenta Demo",
        "pt": "Conta Demo",
        "ru": "Демо аккаунт",
        "zh": "模拟账户",
        "ja": "デモアカウント",
        "ko": "데모 계정",
    },
    
    "btn_real": {
        "id": "Real Account",
        "en": "Real Account",
        "hi": "वास्तविक खाता",
        "ar": "حساب حقيقي",
        "es": "Cuenta Real",
        "pt": "Conta Real",
        "ru": "Реальный аккаунт",
        "zh": "真实账户",
        "ja": "リアルアカウント",
        "ko": "실제 계정",
    },
    
    "btn_start_trading": {
        "id": "🚀 Mulai Trading",
        "en": "🚀 Start Trading",
        "hi": "🚀 ट्रेडिंग शुरू करें",
        "ar": "🚀 ابدأ التداول",
        "es": "🚀 Iniciar Trading",
        "pt": "🚀 Iniciar Trading",
        "ru": "🚀 Начать торговлю",
        "zh": "🚀 开始交易",
        "ja": "🚀 取引開始",
        "ko": "🚀 거래 시작",
    },
    
    "btn_stop_trading": {
        "id": "⏹️ Stop Trading",
        "en": "⏹️ Stop Trading",
        "hi": "⏹️ ट्रेडिंग बंद करें",
        "ar": "⏹️ إيقاف التداول",
        "es": "⏹️ Detener Trading",
        "pt": "⏹️ Parar Trading",
        "ru": "⏹️ Остановить торговлю",
        "zh": "⏹️ 停止交易",
        "ja": "⏹️ 取引停止",
        "ko": "⏹️ 거래 중지",
    },
    
    # Error messages
    "error_not_logged_in": {
        "id": "⚠️ Anda belum login. Gunakan /login untuk masuk.",
        "en": "⚠️ You are not logged in. Use /login to sign in.",
        "hi": "⚠️ आप लॉग इन नहीं हैं। साइन इन करने के लिए /login का उपयोग करें।",
        "ar": "⚠️ لم تقم بتسجيل الدخول. استخدم /login للدخول.",
        "es": "⚠️ No has iniciado sesión. Usa /login para entrar.",
        "pt": "⚠️ Você não está logado. Use /login para entrar.",
        "ru": "⚠️ Вы не авторизованы. Используйте /login для входа.",
        "zh": "⚠️ 您尚未登录。使用 /login 登录。",
        "ja": "⚠️ ログインしていません。/login でサインインしてください。",
        "ko": "⚠️ 로그인되어 있지 않습니다. /login을 사용하여 로그인하세요.",
    },
    
    "error_generic": {
        "id": "❌ Terjadi kesalahan: {error}",
        "en": "❌ An error occurred: {error}",
        "hi": "❌ एक त्रुटि हुई: {error}",
        "ar": "❌ حدث خطأ: {error}",
        "es": "❌ Ocurrió un error: {error}",
        "pt": "❌ Ocorreu um erro: {error}",
        "ru": "❌ Произошла ошибка: {error}",
        "zh": "❌ 发生错误：{error}",
        "ja": "❌ エラーが発生しました：{error}",
        "ko": "❌ 오류가 발생했습니다: {error}",
    },
}

# Language code mapping for variants
LANGUAGE_MAP = {
    "en-us": "en",
    "en-gb": "en",
    "pt-br": "pt",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "es-es": "es",
    "es-mx": "es",
}

def get_text(key: str, lang: str = "id", **params) -> str:
    """
    Get translated text for a key
    
    Args:
        key: Message key
        lang: Language code
        **params: Parameters to substitute in message
        
    Returns:
        Translated text with parameters substituted
    """
    # Normalize language code
    lang = lang.lower()
    lang = LANGUAGE_MAP.get(lang, lang)
    
    # Get message
    messages = MESSAGES.get(key, {})
    
    # Try requested language, fallback to Indonesian, then English
    text = messages.get(lang) or messages.get("id") or messages.get("en", key)
    
    # Substitute parameters
    if params:
        try:
            text = text.format(**params)
        except KeyError as e:
            logger.warning(f"Missing parameter in message {key}: {e}")
    
    return text

def detect_language(telegram_code: Optional[str]) -> str:
    """
    Detect language from Telegram language code
    
    Args:
        telegram_code: Telegram user's language_code
        
    Returns:
        Supported language code
    """
    if not telegram_code:
        return "id"
    
    code = telegram_code.lower()
    code = LANGUAGE_MAP.get(code, code)
    
    # Extract base language if variant
    if "-" in code:
        code = code.split("-")[0]
    if "_" in code:
        code = code.split("_")[0]
    
    if code in SUPPORTED_LANGUAGES:
        return code
    
    return "id"  # Default to Indonesian

def get_user_language(user_id: int, fallback: str = "id") -> str:
    """Get user's language preference"""
    return _user_languages.get(user_id, fallback)

def set_user_language(user_id: int, lang: str):
    """Set user's language preference"""
    if lang in SUPPORTED_LANGUAGES:
        _user_languages[user_id] = lang
        logger.debug(f"Set language for user {user_id}: {lang}")

def get_language_list() -> str:
    """Get formatted list of supported languages"""
    lines = []
    for code, name in sorted(SUPPORTED_LANGUAGES.items(), key=lambda x: x[1]):
        lines.append(f"  • {code}: {name}")
    return "\n".join(lines)
