"""
main.py
Entrypoint — runs Userbot (Telethon) and Controller Bot concurrently via asyncio.
"""

import asyncio
import logging
import sys

from telethon import TelegramClient
from telethon.sessions import StringSession

import database as db
from config import config
from forwarder import Forwarder
from dashboard import register_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Initialising database…")
    db.init_db()

    # ── Userbot (personal account) ───────────────────────────────────────────
    logger.info("Starting Userbot…")
    userbot = TelegramClient(
        StringSession(config.SESSION_STRING),
        config.API_ID,
        config.API_HASH,
    )
    await userbot.start()
    me = await userbot.get_me()
    logger.info("Userbot logged in as: %s (id=%s)", me.username or me.first_name, me.id)

    # ── Forwarder engine ─────────────────────────────────────────────────────
    forwarder = Forwarder(userbot)

    # Auto-resume if was running before restart
    if db.get_setting("running") == "1":
        logger.info("Resuming forwarder (was running before restart).")
        forwarder.start()

    # ── Controller Bot ───────────────────────────────────────────────────────
    logger.info("Starting Controller Bot…")
    bot = TelegramClient(
        "bot_session",
        config.API_ID,
        config.API_HASH,
    )
    await bot.start(bot_token=config.BOT_TOKEN)
    bot_me = await bot.get_me()
    logger.info("Controller Bot started: @%s", bot_me.username)

    register_handlers(bot)

    # Notify admin on startup
    try:
        await bot.send_message(
            config.ADMIN_USER_ID,
            f"✅ **System online**\n"
            f"Userbot: `{me.username or me.first_name}`\n"
            f"Forwarder: {'▶️ Running' if forwarder.is_running else '⏸ Paused'}\n\n"
            "Use /start to open the dashboard.",
        )
    except Exception as exc:
        logger.warning("Could not send startup message: %s", exc)

    logger.info("All systems up. Running until interrupted.")

    # Run both clients concurrently
    await asyncio.gather(
        userbot.run_until_disconnected(),
        bot.run_until_disconnected(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
