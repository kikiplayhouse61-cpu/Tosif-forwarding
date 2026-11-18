# Telegram Auto-Forwarder

A production-ready Telegram auto-forwarding system using your **personal account** (Userbot via Telethon) + a **Controller Bot** with an inline keyboard dashboard.

---

## Architecture

```
┌─────────────────────────────────────┐
│          Railway Worker             │
│                                     │
│  ┌────────────┐  ┌───────────────┐  │
│  │  Userbot   │  │ Controller Bot│  │
│  │ (Telethon) │  │  (Bot Token)  │  │
│  └────┬───────┘  └──────┬────────┘  │
│       │                 │           │
│  ┌────▼─────────────────▼────────┐  │
│  │       Forwarder Engine         │  │
│  │  • Per-group independent timer │  │
│  │  • 60s ± jitter gap           │  │
│  │  • FloodWait auto-recovery    │  │
│  └────────────────────────────────┘  │
│               │                      │
│  ┌────────────▼──────────────────┐  │
│  │       SQLite Database          │  │
│  │  groups / timestamps /         │  │
│  │  settings / message / logs    │  │
│  └────────────────────────────────┘  │
└─────────────────────────────────────┘
```

---

## Step 1 — Get API Credentials

1. Go to **https://my.telegram.org/auth**
2. Log in with your phone number
3. Click **API development tools**
4. Create an app → copy `api_id` and `api_hash`

---

## Step 2 — Generate SESSION_STRING

Run this **once** on your PC, Mac, or Termux (Android):

```bash
# Install dependencies
pip install telethon python-dotenv

# Run generator
python session_generator.py
```

- Enter your `API_ID` and `API_HASH`
- Telegram will send an OTP to your account
- Enter it when prompted
- If 2FA is enabled, enter your password
- **Copy the SESSION_STRING printed at the end**

> ⚠️ Keep this string secret — it gives full access to your Telegram account.

---

## Step 3 — Create Controller Bot

1. Open **@BotFather** on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the **bot token**

---

## Step 4 — Get your Telegram User ID

1. Message **@userinfobot** on Telegram
2. It will reply with your numeric user ID
3. Copy it (e.g. `987654321`)

---

## Step 5 — Deploy on Railway

### Option A: Deploy via GitHub (recommended)

1. Fork / push this project to a GitHub repository
2. Go to **https://railway.app** → **New Project** → **Deploy from GitHub repo**
3. Select your repository
4. Railway will auto-detect Python and use `Procfile`

### Option B: Deploy via Railway CLI

```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

### Set Environment Variables

In the Railway dashboard → your service → **Variables**, add:

| Key | Value |
|-----|-------|
| `API_ID` | Your numeric API ID |
| `API_HASH` | Your API hash string |
| `SESSION_STRING` | Output from session_generator.py |
| `BOT_TOKEN` | Your bot token from BotFather |
| `ADMIN_USER_ID` | Your numeric Telegram user ID |
| `DB_PATH` | `forwarder.db` (default) |

### Add a Persistent Volume (important!)

SQLite data must survive restarts:

1. Railway dashboard → your service → **Volumes**
2. Add volume → mount path: `/app` (or wherever your working dir is)
3. Railway will persist `forwarder.db` across deploys

> Alternatively, switch `DB_PATH` to a mounted path like `/data/forwarder.db`
> and mount the volume at `/data`.

---

## Step 6 — Use the Controller Bot

Open your bot on Telegram and send `/start`.

### Dashboard buttons:

| Button | Action |
|--------|--------|
| 📋 Status | Live status with per-group countdowns |
| ✉️ Set Message | Send any message to set the broadcast content |
| ➕ Add Group | Add group by ID / @username / invite link |
| ➖ Remove Group | Remove a group from the list |
| ⏱ Set Interval | Set global or per-group cycle interval |
| 📊 Groups List | Full list with timing info |
| ▶️ Start / ⏸ Pause | Toggle the forwarder on/off |
| ⏹ Stop & Reset | Stop the forwarder |
| 🌊 Flood Logs | View recent FloodWait events |
| 🔄 Refresh | Refresh the status panel |

### Setting a message:

1. Tap **✉️ Set Message**
2. Send **any** Telegram message — text, photo, video, sticker, document
3. That message becomes the broadcast content
4. Send a new message any time to update it

### Adding groups:

1. Tap **➕ Add Group**
2. Send the group's `@username`, numeric Chat ID, or `https://t.me/+...` invite link
3. The bot verifies your Userbot is a member before adding

### Setting intervals:

- **Global interval**: how often the cycle repeats (default: 17 min)
- **Per-group interval**: override for a specific group
- **Gap between groups**: always 60 ± 2–5 seconds (hardcoded for anti-ban)

---

## Timing Logic

```
Cycle start
    │
    ▼
Group 1 ──► send ──► stamp last_sent_at = T1
    │
    ▼  wait 60 ± jitter seconds
    │
Group 2 ──► send ──► stamp last_sent_at = T2 (= T1 + ~60s)
    │
    ▼  wait 60 ± jitter seconds
    │
Group N ──► send ──► stamp last_sent_at = TN
```

Each group's **next send** is counted from **its own** `last_sent_at`, not from when Group 1 sent. So Group 20 (which received its message ~19 minutes after Group 1) will start its countdown from that later timestamp.

---

## FloodWait Handling

If Telegram returns a `FloodWait` error:
1. The wait duration is logged to `flood_log` table
2. The system sleeps for `wait_seconds + 2–6s` random buffer
3. The send is retried automatically
4. Up to 3 retries per group per cycle

---

## File Structure

```
tg_forwarder/
├── main.py               # Entrypoint — runs userbot + bot concurrently
├── config.py             # Env vars loader
├── database.py           # SQLite persistence (groups, timestamps, settings, logs)
├── forwarder.py          # Core engine: per-group timer, 60s gap, FloodWait
├── dashboard.py          # Controller bot: commands + inline keyboard handlers
├── session_generator.py  # Run once to generate SESSION_STRING
├── requirements.txt
├── Procfile              # Railway worker config
├── railway.json          # Railway deployment config
├── .env.example          # Template for environment variables
└── README.md
```

---

## Troubleshooting

**Bot doesn't respond:**
- Check `ADMIN_USER_ID` is correct (must be numeric)
- Ensure bot token is valid

**Userbot can't join groups:**
- Make sure your Telegram account has manually joined the target groups
- Use the exact same phone number that generated the SESSION_STRING

**FloodWait loops:**
- Reduce the number of groups or increase the cycle interval
- The system handles this automatically but frequent floods may indicate too-aggressive settings

**Railway restarts losing data:**
- Add a persistent volume mounted at the directory where `forwarder.db` lives
- Or use `DB_PATH=/data/forwarder.db` with volume mounted at `/data`

**Session expired:**
- Re-run `session_generator.py` to generate a new session string
- Update the `SESSION_STRING` environment variable in Railway
