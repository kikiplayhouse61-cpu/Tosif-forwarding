import asyncio
import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import config
from database import init_db
from forwarder import Forwarder
from dashboard import register_handlers


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger(__name__)


async def main():
    init_db()

    logger.info("Starting personal Telegram account...")

    userbot = TelegramClient(
        StringSession(config.SESSION_STRING),
        config.API_ID,
        config.API_HASH
    )

    await userbot.start()

    me = await userbot.get_me()

    logger.info(
        "Personal account connected: %s",
        me.username or me.first_name
    )

    forwarder = Forwarder(userbot)

    if config.BOT_TOKEN:
        logger.info("Starting controller bot...")

        bot = TelegramClient(
            "bot_session",
            config.API_ID,
            config.API_HASH
        )

        await bot.start(bot_token=config.BOT_TOKEN)

        register_handlers(bot, forwarder)

        try:
            await bot.send_message(
                config.ADMIN_USER_ID,
                "✅ **Forwarder system online**\n\n"
                f"Personal account: `{me.username or me.first_name}`\n"
                "Send /start to open the dashboard."
            )
        except Exception as exc:
            logger.warning("Startup notification failed: %s", exc)

        if config_running := __import__(
            "database"
        ).get_setting("running", "0") == "1":
            forwarder.start()

        logger.info("Both Telegram clients are running.")

        await asyncio.gather(
            userbot.run_until_disconnected(),
            bot.run_until_disconnected()
        )

    else:
        logger.error("BOT_TOKEN is missing.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
