# Deploy ke Koyeb Free Tier (24/7 Online)

## Langkah-langkah Deployment

### 1. Persiapan Repository
Push project ini ke GitHub repository Anda.

### 2. Buat Akun Koyeb
1. Daftar di https://app.koyeb.com
2. Pilih free tier

### 3. Deploy dari GitHub
1. Klik "Create App"
2. Pilih "GitHub" sebagai source
3. Connect repository Anda
4. Pilih branch (main/master)

### 4. Konfigurasi Build
- **Builder**: Docker (otomatis terdeteksi dari Dockerfile)
- **Port**: 8000

### 5. Set Environment Variables
Di bagian "Environment variables", tambahkan:

| Variable | Value | Keterangan |
|----------|-------|------------|
| `TELEGRAM_BOT_TOKEN` | `your_bot_token` | Token dari @BotFather |
| `DERIV_APP_ID` | `your_app_id` | (Opsional) App ID Deriv |
| `APP_URL` | `https://your-app.koyeb.app` | URL aplikasi setelah deploy |

### 6. Deploy
Klik "Deploy" dan tunggu hingga selesai.

## Fitur Keep-Alive 24/7

Bot ini sudah dilengkapi fitur **self-ping keep-alive** yang akan:
- Melakukan ping otomatis setiap 4 menit ke `/api/health`
- Mencegah app sleep karena tidak ada traffic
- Menjaga bot tetap aktif 24 jam

### Cara Kerja:
1. Saat startup, `keep_alive_service` mulai berjalan
2. Setiap 240 detik, service melakukan HTTP request ke endpoint health
3. Koyeb melihat ada traffic, sehingga tidak men-sleep app

### Monitoring Keep-Alive:
Cek status di: `https://your-app.koyeb.app/api/keep-alive/status`

Response:
```json
{
  "running": true,
  "interval_seconds": 240,
  "ping_count": 15,
  "last_ping": "2024-01-01T12:00:00",
  "app_url": "https://your-app.koyeb.app"
}
```

## Konfigurasi Tambahan (Opsional)

### Menggunakan UptimeRobot (Backup)
Untuk keamanan tambahan, setup UptimeRobot:
1. Daftar di https://uptimerobot.com (gratis)
2. Tambah monitor baru
3. Type: HTTP(s)
4. URL: `https://your-app.koyeb.app/api/health`
5. Interval: 5 menit

## Endpoints

| Endpoint | Keterangan |
|----------|------------|
| `/api/health` | Health check |
| `/api/keep-alive/status` | Status keep-alive service |
| `/terminal` | Terminal trading |
| `/digitpad` | DigitPad strategy |
| `/sniper` | Sniper strategy |

## Troubleshooting

### App Sleep Meskipun Ada Keep-Alive
1. Pastikan `APP_URL` sudah diset dengan benar
2. Cek logs untuk error
3. Gunakan UptimeRobot sebagai backup

### Bot Tidak Merespon
1. Cek `TELEGRAM_BOT_TOKEN` sudah benar
2. Lihat logs di Koyeb dashboard
3. Restart service jika perlu

## Tips Free Tier Koyeb
- Free tier: 1 app dengan 256MB RAM
- Selama ada traffic, app tidak sleep
- Dengan keep-alive, app berjalan 24/7
