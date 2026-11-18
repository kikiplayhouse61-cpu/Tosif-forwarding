"""
dashboard.py
Telegram Bot controller — inline keyboard dashboard.
Strictly restricted to ADMIN_USER_ID.
"""

import asyncio
import logging
import time
from typing import Optional

from telethon import TelegramClient, events, Button
from telethon.tl.custom import Message

import database as db
from config import config
from forwarder import get_forwarder

logger = logging.getLogger(__name__)

# ── state machine for multi-step inputs ─────────────────────────────────────
# key: admin_user_id, value: {"state": str, ...}
_user_state: dict = {}

STATE_IDLE = "idle"
STATE_AWAIT_MSG = "await_msg"
STATE_AWAIT_GROUP_ADD = "await_group_add"
STATE_AWAIT_GROUP_REMOVE = "await_group_remove"
STATE_AWAIT_GLOBAL_INTERVAL = "await_global_interval"
STATE_AWAIT_GROUP_FOR_INTERVAL = "await_group_for_interval"
STATE_AWAIT_INTERVAL_VALUE = "await_interval_value"


def _admin_only(event) -> bool:
    return event.sender_id == config.ADMIN_USER_ID


def _fmt_countdown(seconds_remaining: float) -> str:
    if seconds_remaining <= 0:
        return "**due now**"
    m = int(seconds_remaining // 60)
    s = int(seconds_remaining % 60)
    return f"{m}m {s:02d}s"


def _fmt_ago(seconds_ago: float) -> str:
    if seconds_ago < 60:
        return f"{int(seconds_ago)}s ago"
    m = int(seconds_ago // 60)
    s = int(seconds_ago % 60)
    return f"{m}m {s:02d}s ago"


async def _status_text() -> str:
    fwd = get_forwarder()
    running = fwd and fwd.is_running
    groups = db.get_all_groups()
    global_interval = int(db.get_setting("cycle_interval_minutes") or 17)
    total_sent = db.get_setting("total_sent") or "0"
    msg = db.get_latest_message()
    has_msg = msg is not None
    now = time.time()

    floods = db.get_recent_flood_logs(5)
    flood_text = ""
    if floods:
        flood_text = "\n\n**⚠️ Recent FloodWaits:**\n"
        for f in floods:
            ago = _fmt_ago(now - f["occurred_at"])
            flood_text += f"  • {f['chat_id']} — waited {f['wait_secs']}s ({ago})\n"

    group_lines = ""
    for g in groups:
        interval_mins = g["cycle_interval"] if g["cycle_interval"] is not None else global_interval
        interval_secs = interval_mins * 60
        last_sent = g["last_sent_at"] or 0
        elapsed = now - last_sent if last_sent else None
        remaining = max(0, interval_secs - (elapsed or interval_secs))
        title = g["title"] or g["chat_id"]
        if last_sent:
            ago_str = _fmt_ago(elapsed)
            cd_str = _fmt_countdown(remaining)
            group_lines += f"  • **{title}** — sent {ago_str} | next in {cd_str}\n"
        else:
            group_lines += f"  • **{title}** — never sent | ready\n"

    status_icon = "🟢 Running" if running else "🔴 Paused"
    cur_group = fwd.current_group if fwd else None
    cur_line = f"\n🔄 Currently sending to: `{cur_group}`" if cur_group else ""

    return (
        f"**📊 Auto-Forwarder Dashboard**\n\n"
        f"Status: {status_icon}{cur_line}\n"
        f"Message set: {'✅' if has_msg else '❌ Not set'}\n"
        f"Global cycle interval: **{global_interval} min**\n"
        f"Gap between groups: **60 ± 2–5 s**\n"
        f"Total groups: **{len(groups)}**\n"
        f"Total messages sent: **{total_sent}**\n\n"
        f"**📋 Per-Group Status:**\n"
        f"{group_lines or '  (no groups added)'}"
        f"{flood_text}"
    )


def _main_keyboard(running: bool):
    toggle_label = "⏸ Pause" if running else "▶️ Start"
    return [
        [Button.inline("📋 Status", b"status"), Button.inline("✉️ Set Message", b"set_msg")],
        [Button.inline("➕ Add Group", b"add_group"), Button.inline("➖ Remove Group", b"rm_group")],
        [Button.inline("⏱ Set Interval", b"set_interval"), Button.inline("📊 Groups List", b"groups_list")],
        [Button.inline(toggle_label, b"toggle"), Button.inline("⏹ Stop & Reset", b"stop")],
        [Button.inline("🌊 Flood Logs", b"flood_logs"), Button.inline("🔄 Refresh", b"refresh")],
    ]


def register_handlers(bot: TelegramClient) -> None:

    # ── /start ───────────────────────────────────────────────────────────────

    @bot.on(events.NewMessage(pattern="/start"))
    async def cmd_start(event):
        if not _admin_only(event):
            return
        fwd = get_forwarder()
        running = fwd and fwd.is_running
        await event.respond(
            await _status_text(),
            buttons=_main_keyboard(running),
        )
        raise events.StopPropagation

    # ── /help ────────────────────────────────────────────────────────────────

    @bot.on(events.NewMessage(pattern="/help"))
    async def cmd_help(event):
        if not _admin_only(event):
            return
        await event.respond(
            "**Commands:**\n"
            "/start — open dashboard\n"
            "/status — live status\n"
            "/start_fw — start forwarder\n"
            "/pause_fw — pause forwarder\n\n"
            "Use the inline buttons for everything else."
        )
        raise events.StopPropagation

    # ── /status ──────────────────────────────────────────────────────────────

    @bot.on(events.NewMessage(pattern="/status"))
    async def cmd_status(event):
        if not _admin_only(event):
            return
        fwd = get_forwarder()
        running = fwd and fwd.is_running
        await event.respond(await _status_text(), buttons=_main_keyboard(running))
        raise events.StopPropagation

    # ── /start_fw /pause_fw ──────────────────────────────────────────────────

    @bot.on(events.NewMessage(pattern="/start_fw"))
    async def cmd_start_fw(event):
        if not _admin_only(event):
            return
        fwd = get_forwarder()
        if not fwd:
            await event.respond("❌ Forwarder not initialised yet.")
            return
        if fwd.is_running:
            await event.respond("Already running.")
        else:
            fwd.start()
            await event.respond("▶️ Forwarder started.")
        raise events.StopPropagation

    @bot.on(events.NewMessage(pattern="/pause_fw"))
    async def cmd_pause_fw(event):
        if not _admin_only(event):
            return
        fwd = get_forwarder()
        if not fwd:
            await event.respond("❌ Forwarder not initialised.")
            return
        fwd.pause()
        await event.respond("⏸ Forwarder paused.")
        raise events.StopPropagation

    # ── inline button callbacks ──────────────────────────────────────────────

    @bot.on(events.CallbackQuery)
    async def cb_handler(event):
        if not _admin_only(event):
            await event.answer("⛔ Unauthorised.")
            return

        data = event.data.decode()
        fwd = get_forwarder()
        running = fwd and fwd.is_running

        # ── status / refresh ─────────────────────────────────────────────────
        if data in ("status", "refresh"):
            await event.edit(
                await _status_text(),
                buttons=_main_keyboard(running),
            )

        # ── toggle start/pause ───────────────────────────────────────────────
        elif data == "toggle":
            if not fwd:
                await event.answer("Forwarder not ready.")
                return
            if running:
                fwd.pause()
                await event.answer("⏸ Paused.")
            else:
                if not db.get_latest_message():
                    await event.answer("❌ Set a message first!")
                    return
                fwd.start()
                await event.answer("▶️ Started.")
            await event.edit(
                await _status_text(),
                buttons=_main_keyboard(not running),
            )

        # ── stop & reset ─────────────────────────────────────────────────────
        elif data == "stop":
            if fwd:
                fwd.pause()
            await event.answer("⏹ Stopped.")
            await event.edit(
                await _status_text(),
                buttons=_main_keyboard(False),
            )

        # ── set message ──────────────────────────────────────────────────────
        elif data == "set_msg":
            _user_state[config.ADMIN_USER_ID] = {"state": STATE_AWAIT_MSG}
            await event.answer()
            await event.respond(
                "✉️ **Set Broadcast Message**\n\n"
                "Send me any message now — text, photo, video, sticker, document, etc.\n"
                "Whatever you send will become the new broadcast message.\n\n"
                "Send /cancel to abort."
            )

        # ── add group ────────────────────────────────────────────────────────
        elif data == "add_group":
            _user_state[config.ADMIN_USER_ID] = {"state": STATE_AWAIT_GROUP_ADD}
            await event.answer()
            await event.respond(
                "➕ **Add Group**\n\n"
                "Send me the group's:\n"
                "  • `@username`\n"
                "  • Chat ID (e.g. `-1001234567890`)\n"
                "  • Invite link (https://t.me/+xxxx)\n\n"
                "Your Userbot must be a member of that group.\n"
                "Send /cancel to abort."
            )

        # ── remove group ─────────────────────────────────────────────────────
        elif data == "rm_group":
            groups = db.get_all_groups()
            if not groups:
                await event.answer("No groups to remove.")
                return
            _user_state[config.ADMIN_USER_ID] = {"state": STATE_AWAIT_GROUP_REMOVE}
            await event.answer()
            lines = "\n".join(
                f"  {i+1}. `{g['chat_id']}` — {g['title'] or '(no title)'}"
                for i, g in enumerate(groups)
            )
            await event.respond(
                f"➖ **Remove Group**\n\nCurrent groups:\n{lines}\n\n"
                "Send the Chat ID or @username to remove.\n"
                "Send /cancel to abort."
            )

        # ── groups list ──────────────────────────────────────────────────────
        elif data == "groups_list":
            groups = db.get_all_groups()
            if not groups:
                await event.answer("No groups configured.")
                return
            global_iv = int(db.get_setting("cycle_interval_minutes") or 17)
            now = time.time()
            lines = []
            for i, g in enumerate(groups, 1):
                iv = g["cycle_interval"] if g["cycle_interval"] is not None else global_iv
                last = g["last_sent_at"]
                if last:
                    elapsed = now - last
                    remaining = max(0, iv * 60 - elapsed)
                    timing = f"sent {_fmt_ago(elapsed)}, next in {_fmt_countdown(remaining)}"
                else:
                    timing = "never sent — ready"
                lines.append(
                    f"{i}. **{g['title'] or g['chat_id']}**\n"
                    f"   ID: `{g['chat_id']}` | interval: {iv}m | {timing}"
                )
            await event.answer()
            await event.respond("**📋 Groups:**\n\n" + "\n\n".join(lines))

        # ── set interval ─────────────────────────────────────────────────────
        elif data == "set_interval":
            await event.answer()
            await event.respond(
                "⏱ **Set Interval**\n\n"
                "Choose what to configure:",
                buttons=[
                    [Button.inline("🌍 Global interval", b"interval_global")],
                    [Button.inline("👥 Per-group interval", b"interval_per_group")],
                    [Button.inline("« Back", b"status")],
                ],
            )

        elif data == "interval_global":
            _user_state[config.ADMIN_USER_ID] = {"state": STATE_AWAIT_GLOBAL_INTERVAL}
            await event.answer()
            cur = db.get_setting("cycle_interval_minutes")
            await event.respond(
                f"⏱ Current global interval: **{cur} minutes**\n\n"
                "Send the new interval in **minutes** (e.g. `17`).\n"
                "Send /cancel to abort."
            )

        elif data == "interval_per_group":
            groups = db.get_all_groups()
            if not groups:
                await event.answer("No groups yet.")
                return
            _user_state[config.ADMIN_USER_ID] = {"state": STATE_AWAIT_GROUP_FOR_INTERVAL}
            await event.answer()
            lines = "\n".join(
                f"  {i+1}. `{g['chat_id']}` — {g['title'] or '(no title)'}"
                for i, g in enumerate(groups)
            )
            await event.respond(
                f"👥 **Per-Group Interval**\n\nGroups:\n{lines}\n\n"
                "Send the Chat ID of the group you want to configure.\n"
                "Send /cancel to abort."
            )

        # ── flood logs ───────────────────────────────────────────────────────
        elif data == "flood_logs":
            floods = db.get_recent_flood_logs(15)
            if not floods:
                await event.answer("No FloodWait events recorded.")
                return
            now = time.time()
            lines = [
                f"• `{f['chat_id']}` — waited {f['wait_secs']}s "
                f"({_fmt_ago(now - f['occurred_at'])})"
                for f in floods
            ]
            await event.answer()
            await event.respond(
                "**🌊 Recent FloodWait Events (last 15):**\n\n" + "\n".join(lines)
            )

    # ── text message handler (state machine) ─────────────────────────────────

    @bot.on(events.NewMessage)
    async def msg_handler(event: events.NewMessage.Event):
        if not _admin_only(event):
            return
        if event.via_bot_id:
            return

        text = (event.text or "").strip()

        # cancel
        if text.lower() == "/cancel":
            _user_state.pop(config.ADMIN_USER_ID, None)
            await event.respond("❌ Cancelled.")
            return

        state_data = _user_state.get(config.ADMIN_USER_ID, {})
        state = state_data.get("state", STATE_IDLE)

        # ── await broadcast message ──────────────────────────────────────────
        if state == STATE_AWAIT_MSG:
            _user_state.pop(config.ADMIN_USER_ID, None)
            msg = event.message

            if msg.photo:
                file_id = str(msg.photo.id)
                caption = msg.text or ""
                db.save_message(media_type="photo", file_id=file_id, caption=caption)
                await event.respond("✅ Photo message saved!")

            elif msg.video:
                file_id = str(msg.video.id)
                caption = msg.text or ""
                db.save_message(media_type="video", file_id=file_id, caption=caption)
                await event.respond("✅ Video message saved!")

            elif msg.document:
                file_id = str(msg.document.id)
                caption = msg.text or ""
                db.save_message(media_type="document", file_id=file_id, caption=caption)
                await event.respond("✅ Document message saved!")

            elif msg.sticker:
                file_id = str(msg.sticker.id)
                db.save_message(media_type="sticker", file_id=file_id)
                await event.respond("✅ Sticker message saved!")

            elif msg.text:
                db.save_message(text=msg.text)
                await event.respond(f"✅ Text message saved:\n\n{msg.text[:200]}")

            else:
                await event.respond("❌ Unsupported message type.")
            return

        # ── await group add ───────────────────────────────────────────────────
        if state == STATE_AWAIT_GROUP_ADD:
            if not text:
                await event.respond("❌ Please send a valid group ID, @username, or link.")
                return
            _user_state.pop(config.ADMIN_USER_ID, None)

            fwd = get_forwarder()
            if not fwd:
                await event.respond("❌ Forwarder not ready.")
                return

            await event.respond("🔍 Checking membership…")
            is_member, title = await fwd.check_membership(text)

            if not is_member:
                await event.respond(
                    f"❌ Your Userbot is **not a member** of that group.\n"
                    f"Info: {title}\n\n"
                    "Join the group with your Userbot account first, then try again."
                )
                return

            added = db.add_group(text, title)
            if added:
                await event.respond(f"✅ Added: **{title}** (`{text}`)")
            else:
                await event.respond(f"ℹ️ Group `{text}` is already in the list.")
            return

        # ── await group remove ────────────────────────────────────────────────
        if state == STATE_AWAIT_GROUP_REMOVE:
            if not text:
                return
            _user_state.pop(config.ADMIN_USER_ID, None)
            removed = db.remove_group(text)
            if removed:
                await event.respond(f"✅ Removed group `{text}`.")
            else:
                await event.respond(f"❌ Group `{text}` not found in list.")
            return

        # ── await global interval ─────────────────────────────────────────────
        if state == STATE_AWAIT_GLOBAL_INTERVAL:
            _user_state.pop(config.ADMIN_USER_ID, None)
            try:
                mins = int(text)
                assert 1 <= mins <= 1440
            except (ValueError, AssertionError):
                await event.respond("❌ Please send a number between 1 and 1440.")
                return
            db.set_setting("cycle_interval_minutes", str(mins))
            await event.respond(f"✅ Global cycle interval set to **{mins} minutes**.")
            return

        # ── await group for per-group interval ───────────────────────────────
        if state == STATE_AWAIT_GROUP_FOR_INTERVAL:
            group = db.get_group(text)
            if not group:
                await event.respond(f"❌ Group `{text}` not found.")
                _user_state.pop(config.ADMIN_USER_ID, None)
                return
            _user_state[config.ADMIN_USER_ID] = {
                "state": STATE_AWAIT_INTERVAL_VALUE,
                "target_chat_id": text,
            }
            cur_iv = group["cycle_interval"] or db.get_setting("cycle_interval_minutes")
            await event.respond(
                f"⏱ Current interval for `{text}`: **{cur_iv} min**\n\n"
                "Send the new interval in **minutes**.\n"
                "Send `0` to revert to global interval.\n"
                "Send /cancel to abort."
            )
            return

        # ── await per-group interval value ────────────────────────────────────
        if state == STATE_AWAIT_INTERVAL_VALUE:
            chat_id = state_data.get("target_chat_id")
            _user_state.pop(config.ADMIN_USER_ID, None)
            try:
                mins = int(text)
                assert 0 <= mins <= 1440
            except (ValueError, AssertionError):
                await event.respond("❌ Please send a number between 0 and 1440.")
                return
            if mins == 0:
                db.set_group_cycle_interval(chat_id, None)
                await event.respond(f"✅ Group `{chat_id}` now uses the global interval.")
            else:
                db.set_group_cycle_interval(chat_id, mins)
                await event.respond(
                    f"✅ Group `{chat_id}` interval set to **{mins} minutes**."
                )
            return
