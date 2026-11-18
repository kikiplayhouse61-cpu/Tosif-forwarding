"""
forwarder.py
Core forwarding engine.

Cycle logic:
  1. Determine which groups are due (last_sent_at + cycle_interval <= now).
  2. For each due group, send with a 60 ± jitter second gap between consecutive sends.
  3. Immediately after sending to a group, stamp last_sent_at = time.time() for THAT group.
     This means Group 20 starts its own independent countdown from when it actually received
     the message, not from when Group 1 did.
  4. FloodWait is caught, logged, and slept through; the same group is retried in the next tick.
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
from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser

import database as db
from config import config

logger = logging.getLogger(__name__)

# Global reference so dashboard can query state
_forwarder_instance: Optional["Forwarder"] = None

PER_MSG_DELAY_BASE = 60       # seconds between groups
JITTER_MIN = 2
JITTER_MAX = 5
SCHEDULER_TICK = 30           # seconds between scheduler wakes


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
                logger.warning(
                    "FloodWait %ds for %s, sleeping...", wait, chat_id
                )
                db.log_flood(chat_id, fwe.seconds)
                db.log_send(chat_id, f"floodwait:{fwe.seconds}")
                await asyncio.sleep(wait)
                # retry

            except (
                ChatWriteForbiddenError,
                UserBannedInChannelError,
                ChannelPrivateError,
                ChatAdminRequiredError,
            ) as perm_err:
                logger.error(
                    "Permission error on %s: %s — skipping.", chat_id, perm_err
                )
                db.log_send(chat_id, f"perm_error: {perm_err}")
                return

            except Exception as exc:
                logger.error(
                    "Send attempt %d/%d failed for %s: %s",
                    attempt,
                    retries,
                    chat_id,
                    exc,
            await self.userbot.send_message(peer, text)

    async def _resolve_peer(self, chat_id: str):
        """
        Accepts:
          - numeric chat id  (e.g. "-1001234567890" or "1234567890")
          - @username
          - t.me/invite_link (joinchat/+ links)
        """
        s = str(chat_id).strip()
        if s.startswith("https://t.me/") or s.startswith("t.me/"):
            # Invite/public link — get_entity handles both
            return await self.userbot.get_input_entity(s)
        try:
            numeric = int(s)
            return await self.userbot.get_input_entity(numeric)
        except ValueError:
            pass
        # @username or bare username
        return await self.userbot.get_input_entity(s)

    # ── membership check ─────────────────────────────────────────────────────

    async def check_membership(self, chat_id: str) -> tuple[bool, str]:
        """
        Returns (is_member: bool, title: str).
        Just verifies the entity resolves — if userbot can get_entity,
        it has access. Trust the user that their account is a member.
        """
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
          
