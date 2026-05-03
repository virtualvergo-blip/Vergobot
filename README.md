# 🤖 Meme Coin AI Agent

Agent AI yang memantau channel Telegram signal meme coin, mempelajari pola pump/dump, dan mengirim notifikasi prediksi otomatis.

## 🏗 Arsitektur

```
Telegram Channel Signal
        ↓
  Channel Listener (Telethon)
        ↓
  Extract Contract Address
        ↓
  Fetch Price Data (DexScreener FREE)
        ↓
  Start Multi-Timeframe Monitor (1s/5s/15s/30s/1m/5m/10m)
        ↓
  AI Analysis (Groq - Llama 3.3 70B - FREE)
        ↓
  Save Pattern ke SQLite
        ↓
  Send Alert → Telegram Bot → Anda
```

## ⚡ Tech Stack

| Komponen | Tool | Biaya |
|---|---|---|
| AI Analysis | Groq (Llama 3.3 70B) | **Gratis** |
| Price Data | DexScreener API | **Gratis** |
| Channel Monitor | Telethon | **Gratis** |
| Database | SQLite (local) | **Gratis** |
| Hosting | Railway | ~$5/bulan |

---

## 🚀 Setup Step-by-Step

### 1. Telegram API Credentials

1. Buka https://my.telegram.org/apps
2. Login dengan nomor HP Anda
3. Buat aplikasi baru → catat **API_ID** dan **API_HASH**

### 2. Buat Telegram Bot

1. Chat `@BotFather` di Telegram
2. Kirim `/newbot` → ikuti instruksi
3. Catat **BOT_TOKEN**
4. Chat `@userinfobot` → catat **YOUR_CHAT_ID**

### 3. Groq API Key (Gratis)

1. Daftar di https://console.groq.com
2. API Keys → Create → catat **GROQ_API_KEY**
3. Free tier: 14,400 requests/hari (lebih dari cukup)

### 4. Generate Session String (PENTING untuk Railway)

Jalankan **secara lokal** sebelum deploy:

```bash
# Clone/copy project ke komputer lokal
pip install telethon python-dotenv

# Isi .env dulu dengan API_ID, API_HASH, TELEGRAM_PHONE
cp .env.example .env
nano .env

# Generate session
python generate_session.py
```

Ikuti instruksi, masukkan kode verifikasi dari Telegram. Copy session string yang dihasilkan.

### 5. Deploy ke Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Buat project baru
railway init

# Deploy
railway up
```

### 6. Set Environment Variables di Railway

Di Railway Dashboard → Variables, tambahkan:

```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
TELEGRAM_PHONE=+628xxxxxxxxxx
TELEGRAM_SESSION_STRING=<hasil dari generate_session.py>
TELEGRAM_BOT_TOKEN=123456789:ABCdef...
YOUR_CHAT_ID=123456789
GROQ_API_KEY=gsk_...
SIGNAL_CHANNELS=@channel1,@channel2,@channel3
MONITOR_DURATION_MINUTES=60
MIN_CONFIDENCE=0.65
DB_PATH=data/memeagent.db
PORT=8080
```

---

## 📱 Telegram Bot Commands

| Command | Fungsi |
|---|---|
| `/status` | Winrate, total token, statistik |
| `/tokens` | 10 token terakhir yang di-scan |
| `/active` | Token yang sedang dipantau sekarang |
| `/help` | Daftar commands |

---

## 🔔 Jenis Notifikasi

### 1. New Call Detected
Saat call masuk dari channel signal, langsung dapat info:
- Price, market cap, liquidity
- Volume 5m, buy/sell ratio
- Link DexScreener

### 2. AI Prediction Alert
Setelah 30 detik monitoring, AI kirim prediksi:
- **PUMP / DUMP / RUG / CONSOLIDATE / ACCUMULATE**
- Target multiplier (e.g., x3)
- Safe TP (e.g., x2 untuk aman)
- Stop loss %
- Estimasi waktu ke peak
- Confidence level
- Key signals yang terdeteksi

### 3. Pattern Learned
Setelah sesi monitoring selesai (default 60 menit):
- Pattern type yang dipelajari
- Max gain yang terjadi
- Disimpan ke database untuk meningkatkan akurasi

---

## 🧠 Bagaimana AI Belajar

1. Setiap token yang masuk → dipantau 60 menit
2. Price snapshot setiap 5 detik (semua timeframe)
3. Pattern disimpan ke SQLite dengan outcome (naik/turun/rug)
4. Saat analyze token baru, AI dapat context dari 20 pattern terbaru sebagai few-shot examples
5. Semakin banyak token → semakin akurat prediksi

---

## 📊 Database Schema

- `tokens` — Semua token yang pernah di-scan
- `price_snapshots` — History harga per timeframe
- `patterns` — Pola yang dipelajari per token
- `predictions` — Prediksi AI dan hasilnya
- `agent_stats` — Statistik agent

---

## ⚠️ Penting

- **Ini bukan financial advice**
- Pastikan channel signal yang Anda pantau legal
- Groq free tier limit: 14,400 req/hari, ~6,000 token/req
- Jika banyak token masuk, turunkan frekuensi analisis
- SQLite tidak persistent di Railway free tier → upgrade ke Hobby atau tambah volume

---

## 🐛 Troubleshooting

**Session expired**: Jalankan ulang `generate_session.py` dan update env var

**Groq rate limit**: Tambah `MIN_CONFIDENCE` ke 0.8 untuk kurangi API calls

**Token tidak terdeteksi**: Cek format channel di `SIGNAL_CHANNELS` (harus pakai @)

**Database reset**: Railway free tier menghapus data saat redeploy → tambah persistent volume
