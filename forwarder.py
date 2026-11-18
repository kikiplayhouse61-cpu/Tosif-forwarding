"""
forwarder.py
Core forwarding engine.
"""

import asyncio
import random
import time
import logging
from typing import Optional

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    ChatWriteForbiddenError,
    UserBannedInChannelError,
    ChannelPrivateError,
    ChatAdminRequiredError,
)

import database as db
from config import config

logger = logging.getLogger(__name__)

_forwarder_instance: Optional["Forwarder"] = None

PER_MSG_DELAY_BASE = 60
JITTER_MIN = 2
JITTER_MAX = 5
SCHEDULER_TICK = 30


class Forwarder:
    def __init__(self, userbot: TelegramClient):
        self.userbot = userbot
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._current_cycle_group: Optional[str] = None

        global _forwarder_instance
        _forwarder_instance = self

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        db.set_setting("running", "1")
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Forwarder started.")

    def pause(self) -> None:
        self._running = False
        db.set_setting("running", "0")
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        logger.info("Forwarder paused.")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_group(self) -> Optional[str]:
        return self._current_cycle_group

    async def _scheduler_loop(self) -> None:
        logger.info("Scheduler loop started.")
        while self._running:
            try:
                await self._run_due_groups()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Unexpected error in scheduler loop: %s", exc)
            await asyncio.sleep(SCHEDULER_TICK)

    async def _run_due_groups(self) -> None:
        groups = db.get_all_groups()
        if not groups:
            return

        global_interval_mins = int(db.get_setting("cycle_interval_minutes") or 17)
        global_interval_secs = global_interval_mins * 60

        due_groups = []
        now = time.time()

        for g in groups:
            interval_secs = (
                g["cycle_interval"] * 60
                if g["cycle_interval"] is not None
                else global_interval_secs
            )
            last_sent = g["last_sent_at"] or 0
            if now - last_sent >= interval_secs:
                due_groups.append(g)

        if not due_groups:
            return

        logger.info("Cycle: %d groups due for sending.", len(due_groups))

        for idx, group in enumerate(due_groups):
            if not self._running:
                break

            chat_id = group["chat_id"]
            self._current_cycle_group = chat_id

            if idx > 0:
                delay = PER_MSG_DELAY_BASE + random.uniform(JITTER_MIN, JITTER_MAX)
                logger.info("Waiting %.1f s before sending to %s", delay, chat_id)
                await asyncio.sleep(delay)

            if not self._running:
                break

            await self._send_to_group(chat_id)

        self._current_cycle_group = None

    async def _send_to_group(self, chat_id: str) -> None:
        msg = db.get_latest_message()
        if not msg:
            logger.warning("No message set, skipping %s", chat_id)
            return

        try:
            peer = await self._resolve_peer(chat_id)
        except Exception as exc:
            logger.error("Cannot resolve peer %s: %s", chat_id, exc)
            db.log_send(chat_id, f"resolve_error: {exc}")
            return

        retries = 3
        for attempt in range(1, retries + 1):
            try:
                await self._do_send(peer, msg)
                sent_ts = time.time()
                db.update_group_last_sent(chat_id, sent_ts)
                db.log_send(chat_id, "ok")
                db.increment_total_sent()
                logger.info("Sent to %s at %.0f", chat_id, sent_ts)
                return

            except FloodWaitError as fwe:
                wait = fwe.seconds + random.randint(2, 6)
                logger.warning("FloodWait %ds for %s, sleeping...", wait, chat_id)
                db.log_flood(chat_id, fwe.seconds)
                db.log_send(chat_id, f"floodwait:{fwe.seconds}")
                await asyncio.sleep(wait)

            except (
                ChatWriteForbiddenError,
                UserBannedInChannelError,
                ChannelPrivateError,
                ChatAdminRequiredError,
            ) as perm_err:
                logger.error("Permission error on %s: %s — skipping.", chat_id, perm_err)
                db.log_send(chat_id, f"perm_error: {perm_err}")
                return

            except Exception as exc:
                logger.error("Send attempt %d/%d failed for %s: %s", attempt, retries, chat_id, exc)
                if attempt == retries:
                    db.log_send(chat_id, f"error: {exc}")
                else:
                    await asyncio.sleep(5)

    async def _do_send(self, peer, msg: dict) -> None:
        media_type = msg.get("media_type")
        file_id = msg.get("file_id")
        caption = msg.get("caption") or ""
        text = msg.get("text") or ""

        if media_type and file_id:
            await self.userbot.send_file(peer, file=file_id, caption=caption or None)
        else:
            await self.userbot.send_message(peer, text)

    async def _resolve_peer(self, chat_id: str):
        s = str(chat_id).strip()
        if s.startswith("https://t.me/") or s.startswith("t.me/"):
            return await self.userbot.get_input_entity(s)
        try:
            numeric = int(s)
            return await self.userbot.get_input_entity(numeric)
        except ValueError:
            pass
        return await self.userbot.get_input_entity(s)

    async def check_membership(self, chat_id: str) -> tuple[bool, str]:
        try:
            peer = await self._resolve_peer(chat_id)
            entity = await self.userbot.get_entity(peer)
            title = getattr(entity, "title", None) or getattr(entity, "username", str(chat_id))
            return True, title
        except Exception as exc:
            logger.error("Entity resolve error for %s: %s", chat_id, exc)
            return False, str(exc)


def get_forwarder() -> Optional["Forwarder"]:
    return _forwarder_instance
