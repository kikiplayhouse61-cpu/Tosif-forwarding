import asyncio
import logging
import os
import time
import json

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    ChannelPrivateError,
    ChatAdminRequiredError
)
from telethon.tl.types import MessageEntityCustomEmoji
from telethon.utils import get_peer_id

import database as db

logger = logging.getLogger(__name__)

_forwarder_instance = None

MIN_GROUP_GAP = 60
SCHEDULER_TICK = 10


class Forwarder:

    def __init__(self, userbot):
        global _forwarder_instance

        self.userbot = userbot
        self._task = None
        self._running = False
        self._lock = asyncio.Lock()
        self.current_group = None

        _forwarder_instance = self

    @property
    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return

        self._running = True
        db.set_setting("running", "1")
        self._task = asyncio.create_task(self._scheduler_loop())

        logger.info("Forwarder started")

    def pause(self):
        self._running = False
        db.set_setting("running", "0")

        if self._task and not self._task.done():
            self._task.cancel()

        self._task = None
        logger.info("Forwarder paused")

    async def check_membership(self, chat):
        try:
            chat = str(chat).strip()

            try:
                chat = int(chat)
            except ValueError:
                pass

            entity = await self.userbot.get_entity(chat)
            target_id = get_peer_id(entity)

            async for dialog in self.userbot.iter_dialogs():
                if get_peer_id(dialog.entity) == target_id:
                    return True, entity

            return False, entity

        except Exception as exc:
            logger.warning(
                "Membership check failed for %s: %s",
                chat, exc
            )
            return False, None

    async def _scheduler_loop(self):
        while self._running:
            try:
                await self._run_due_groups()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Scheduler error")

            await asyncio.sleep(SCHEDULER_TICK)

    async def _run_due_groups(self):
        async with self._lock:
            groups = db.get_all_groups()
            now = time.time()

            global_interval = int(
                db.get_setting("cycle_interval_minutes", "17")
            )

            due_groups = []

            for group in groups:
                interval = group["cycle_interval"] or global_interval
                last_sent = float(group["last_sent_at"] or 0)

                if now >= last_sent + interval * 60:
                    due_groups.append(group)

            for group in due_groups:
                if not self._running:
                    break

                last_any = float(
                    db.get_setting("last_any_send_at", "0")
                )

                wait_time = MIN_GROUP_GAP - (time.time() - last_any)

                if last_any > 0 and wait_time > 0:
                    await asyncio.sleep(wait_time)

                if not self._running:
                    break

                self.current_group = group["title"] or group["chat_id"]

                success = await self._send_to_group(group)

                if success:
                    sent_at = time.time()
                    db.update_group_last_sent(group["chat_id"], sent_at)
                    db.set_setting("last_any_send_at", sent_at)
                    db.increment_total_sent()

                self.current_group = None

    async def _send_to_group(self, group):
        chat_id = group["chat_id"]

        try:
            entity = await self.userbot.get_entity(int(chat_id))
            await self._do_send(entity)

            db.log_send(chat_id, "ok")
            logger.info("Sent successfully to %s", chat_id)
            return True

        except FloodWaitError as exc:
            db.log_flood(chat_id, exc.seconds)
            db.log_send(chat_id, "flood_wait")

            logger.warning(
                "Telegram FloodWait: waiting %s seconds",
                exc.seconds
            )

            await asyncio.sleep(exc.seconds)
            return False

        except (
            ChatWriteForbiddenError,
            UserBannedInChannelError,
            ChannelPrivateError,
            ChatAdminRequiredError
        ) as exc:
            logger.error("Cannot send to %s: %s", chat_id, exc)
            db.log_send(chat_id, "permission_error")
            return False

        except Exception as exc:
            logger.exception("Send failed for %s: %s", chat_id, exc)
            db.log_send(chat_id, "error")
            return False

    async def _do_send(self, entity):
        message = db.get_latest_message()

        if not message:
            raise RuntimeError("No broadcast message has been configured")

        text = message.get("text") or ""
        media_type = message.get("media_type") or "text"

        entities = []

        for item in message.get("entities", []):
            if item.get("type") == "MessageEntityCustomEmoji":
                entities.append(
                    MessageEntityCustomEmoji(
                        offset=int(item["offset"]),
                        length=int(item["length"]),
                        document_id=int(item["document_id"])
                    )
                )

        if media_type == "sticker":
            path = message.get("file_path")

            if not path or not os.path.isfile(path):
                raise FileNotFoundError(
                    "Saved sticker file is missing. Please set the sticker again."
                )

            await self.userbot.send_file(
                entity,
                path,
                force_document=False
            )

            # Sticker captions are not supported as sticker captions.
            # If a text was included with the sticker, send it separately.
            if text.strip():
                await self.userbot.send_message(
                    entity,
                    text,
                    formatting_entities=entities or None,
                    link_preview=False
                )

        else:
            if not text.strip():
                raise RuntimeError("Saved text message is empty")

            await self.userbot.send_message(
                entity,
                text,
                formatting_entities=entities or None,
                link_preview=False
            )


def get_forwarder():
    return _forwarder_instance
                
