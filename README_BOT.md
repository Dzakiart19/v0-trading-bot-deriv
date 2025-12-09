# Deriv Auto Trading Bot

Bot trading otomatis untuk platform Deriv dengan multi-strategi, money management, dan integrasi Telegram.

## Fitur

- **Multi-Strategy Trading**
  - Multi-Indicator (RSI, EMA, MACD, Stochastic, ADX)
  - LDP (Last Digit Prediction)
  - Tick Analyzer (Pattern Detection)

- **Money Management**
  - Martingale dengan level maksimum
  - Daily loss limit
  - Risk level (Low, Medium, High)

- **Telegram Bot**
  - Login dengan API Token
  - Real-time notifications
  - Interactive commands
  - Multi-language support

- **Web Dashboard**
  - Real-time statistics
  - Trade history
  - Session monitoring

## Instalasi

1. Clone repository
2. Install dependencies:
   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`

3. Copy `.env.example` ke `.env` dan isi konfigurasi:
   \`\`\`bash
   cp .env.example .env
   \`\`\`

4. Jalankan bot:
   \`\`\`bash
   python main.py
   \`\`\`

## Konfigurasi

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| TELEGRAM_BOT_TOKEN | Token dari BotFather | Required |
| DERIV_APP_ID | Deriv API App ID | 1089 |
| WEB_PORT | Port web dashboard | 5000 |
| ADMIN_USERNAME | Admin dashboard username | admin |
| ADMIN_PASSWORD | Admin dashboard password | admin123 |

### Trading Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| DEFAULT_STAKE | Base stake amount | 1.0 |
| MAX_MARTINGALE_LEVEL | Maximum martingale levels | 5 |
| DAILY_LOSS_LIMIT | Stop loss per hari | 50.0 |

## Commands Telegram

| Command | Description |
|---------|-------------|
| /start | Memulai bot |
| /login | Login ke akun Deriv |
| /logout | Keluar dari akun |
| /akun | Info akun dan saldo |
| /autotrade | Mulai auto trading |
| /stop | Hentikan trading |
| /status | Status trading |
| /strategi | Pilih strategi |
| /pair | Pilih pair/symbol |
| /language | Ubah bahasa |
| /help | Bantuan |

## Strategi

### Multi-Indicator
Menggunakan kombinasi 5 indikator teknikal:
- RSI (Relative Strength Index)
- EMA (Exponential Moving Average)
- MACD (Moving Average Convergence Divergence)
- Stochastic Oscillator
- ADX (Average Directional Index)

### LDP (Last Digit Prediction)
Menganalisis pola digit terakhir dari harga untuk memprediksi pergerakan.

### Tick Analyzer
Mendeteksi pola tick untuk prediksi arah pasar.

## Struktur File

\`\`\`
scripts/
├── main.py              # Entry point
├── telegram_bot.py      # Telegram bot handler
├── web_server.py        # Web dashboard
├── deriv_ws.py          # WebSocket connection
├── trading.py           # Trading manager
├── strategy.py          # Multi-indicator strategy
├── ldp_strategy.py      # LDP strategy
├── tick_analyzer.py     # Tick analyzer strategy
├── indicators.py        # Technical indicators
├── symbols.py           # Symbol configuration
├── money_manager.py     # Money management
├── session_manager.py   # Session management
├── user_auth.py         # User authentication
├── i18n.py              # Internationalization
├── event_bus.py         # Event system
├── analytics.py         # Analytics
├── config.py            # Configuration
└── requirements.txt     # Dependencies
\`\`\`

## Keamanan

- Token API disimpan dengan enkripsi
- Rate limiting untuk mencegah spam
- Lockout setelah gagal login berulang
- Session timeout otomatis

## Disclaimer

Bot ini hanya untuk tujuan edukasi. Trading binary options memiliki risiko tinggi. Gunakan dengan bijak dan hanya gunakan dana yang Anda siap untuk kehilangan.
