
# Telegram Forwarder Controller

## Supported broadcast content

- Normal text
- Normal emojis
- Telegram Premium Custom Emojis
- Telegram stickers and Premium stickers

Photos, videos and documents are not supported.

## Environment Variables

| Variable | Value |
|---|---|
| API_ID | Telegram API ID |
| API_HASH | Telegram API Hash |
| SESSION_STRING | Personal Telegram session |
| BOT_TOKEN | Controller bot token |
| ADMIN_USER_ID | Your numeric Telegram user ID |
| DB_PATH | /data/forwarder.db |

## Dashboard

Send `/start` to the controller bot.

The dashboard includes:
- Set Message
- Message Preview
- Add Group
- Remove Group
- Groups List
- Individual Group Timing
- Default Interval
- Statistics
- Flood Logs
- Start / Pause

## Timing

Each group has its own independent interval.

Example:
- Group 1: 10 minutes
- Group 2: 15 minutes
- Group 3: 20 minutes

The scheduler waits at least 60 seconds between sends to different groups.

Telegram FloodWait restrictions are respected.

## Group Membership

Your personal Telegram account must already be a member of every destination group.

The controller bot does not need to be added to destination groups.

## Deployment

Start command:

python main.py

Use a persistent Railway Volume for the database and saved sticker files.
