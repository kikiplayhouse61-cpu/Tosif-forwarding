
import asyncio
import logging
import time

from telethon import TelegramClient, events, Button

import database as db
from config import config
from forwarder import get_forwarder

logger = logging.getLogger(__name__)

_user_states = {}
_dashboard_message_id = None
_dashboard_view = "home"
_auto_refresh_task = None

STATE_IDLE = "idle"
STATE_AWAIT_MSG = "await_msg"
STATE_AWAIT_GROUP_ADD = "await_group_add"
STATE_AWAIT_GLOBAL_INTERVAL = "await_global_interval"
STATE_AWAIT_INTERVAL_VALUE = "await_interval_value"


def _admin_only(event):
    return event.sender_id == config.ADMIN_USER_ID


def _short_name(name, limit=20):
    name = str(name or "Unknown").replace("\n", " ").strip()
    if len(name) > limit:
        return name[:limit - 1] + "…"
    return name


def _format_time(timestamp):
    if not timestamp:
        return "Never"

    return time.strftime("%I:%M %p", time.localtime(timestamp)).lstrip("0")


def _countdown(seconds):
    if seconds <= 0:
        return "Due now"

    minutes = int(seconds // 60)
    secs = int(seconds % 60)

    if minutes:
        return f"{minutes}m {secs:02d}s"

    return f"{secs}s"


def _get_interval(group):
    interval = group.get("cycle_interval")

    if interval is None:
        interval = int(
            db.get_setting("cycle_interval_minutes", "17")
        )

    return int(interval)


def _get_stats():
    try:
        return db.get_send_stats()
    except Exception:
        return {
            "total": 0,
            "success": int(db.get_setting("total_sent", "0")),
            "failed": 0
        }


def _main_keyboard(running):
    toggle = "⏸ Pause" if running else "▶️ Start"

    return [
        [
            Button.inline("📊 Statistics", b"stats"),
            Button.inline("📋 Groups Status", b"groups")
        ],
        [
            Button.inline("✉️ Set Message", b"set_msg"),
            Button.inline("👁 Preview", b"preview")
        ],
        [
            Button.inline("➕ Add Group", b"add_group"),
            Button.inline("➖ Remove Group", b"rm_group")
        ],
        [
            Button.inline("⏱ Timing", b"timing"),
            Button.inline("🌊 Flood Logs", b"flood")
        ],
        [
            Button.inline(toggle, b"toggle"),
            Button.inline("🔄 Refresh", b"home")
        ]
    ]


def _back_keyboard():
    return [[Button.inline("⬅️ Back", b"home")]]


def _build_home():
    fwd = get_forwarder()
    running = bool(fwd and fwd.is_running)

    groups = db.get_all_groups()
    message = db.get_latest_message()

    total_sent = db.get_setting("total_sent", "0")
    interval = db.get_setting("cycle_interval_minutes", "17")

    content = "Not configured"

    if message:
        if message.get("media_type") == "sticker":
            content = "Telegram Sticker"
        else:
            content = "Text / Premium Emoji"

    current = fwd.current_group if fwd else None

    text = (
        "❄️ **SNOW ZONE — FORWARDER**\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Status: {'🟢 Running' if running else '🔴 Paused'}\n"
        f"Total Groups: `{len(groups)}`\n"
        f"Default Interval: `{interval} minutes`\n"
        f"Content: `{content}`\n"
        f"Successful Sends: `{total_sent}`\n"
        f"Current Group: `{current or 'Idle'}`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Select an option below."
    )

    return text, _main_keyboard(running)


def _build_statistics():
    groups = db.get_all_groups()
    stats = _get_stats()

    total_attempts = stats.get("total", 0)
    successful = stats.get("success", 0)
    failed = stats.get("failed", 0)

    interval = db.get_setting("cycle_interval_minutes", "17")

    text = (
        "📊 **STATISTICS**\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Total Attempts: `{total_attempts}`\n"
        f"Successful: `{successful}`\n"
        f"Failed: `{failed}`\n"
        f"Groups: `{len(groups)}`\n"
        f"Default Interval: `{interval} minutes`\n"
        f"Total Successful Sends: "
        f"`{db.get_setting('total_sent', '0')}`\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⏱ **GROUP NEXT SENDING STATUS**\n\n"
    )

    now = time.time()

    if not groups:
        text += "No groups added yet."
    else:
        for index, group in enumerate(groups, 1):
            name = _short_name(
                group.get("title") or group.get("chat_id"),
                20
            )

            last_sent = float(group.get("last_sent_at") or 0)
            interval_seconds = _get_interval(group) * 60

            if last_sent:
                next_time = last_sent + interval_seconds
                remaining = max(0, next_time - now)

                last_text = _format_time(last_sent)
                next_text = _countdown(remaining)

                status = "🟢" if remaining > 0 else "🟡"
            else:
                last_text = "Not sent yet"
                next_text = "Ready"
                status = "🟡"

            text += (
                f"{status} **{index}. {name}**\n"
                f"   Last Sent: `{last_text}`\n"
                f"   Next Sending: `{next_text}`\n\n"
            )

    text += (
        "━━━━━━━━━━━━━━━━━━\n"
        f"Updated: `{_format_time(now)}`"
    )

    return text


def _build_groups():
    groups = db.get_all_groups()

    if not groups:
        return "👥 **GROUPS LIST**\n\nNo groups added."

    text = "👥 **GROUPS LIST**\n━━━━━━━━━━━━━━━━━━\n\n"

    for index, group in enumerate(groups, 1):
        name = _short_name(
            group.get("title") or group.get("chat_id"),
            24
        )

        interval = _get_interval(group)

        text += (
            f"{index}. **{name}**\n"
            f"ID: `{group['chat_id']}`\n"
            f"Interval: `{interval} minutes`\n\n"
        )

    return text


async def _edit_dashboard(bot, text, buttons=None):
    global _dashboard_message_id

    if _dashboard_message_id:
        try:
            await bot.edit_message(
                config.ADMIN_USER_ID,
                _dashboard_message_id,
                text,
                buttons=buttons
            )
            return
        except Exception as exc:
            logger.debug("Dashboard edit: %s", exc)

    sent = await bot.send_message(
        config.ADMIN_USER_ID,
        text,
        buttons=buttons
    )

    _dashboard_message_id = sent.id


async def _show_home(bot):
    global _dashboard_view

    _dashboard_view = "home"

    text, buttons = _build_home()

    await _edit_dashboard(bot, text, buttons)


async def _auto_refresh(bot):
    global _dashboard_view

    while True:
        try:
            await asyncio.sleep(15)

            if _dashboard_view == "stats":
                await _edit_dashboard(
                    bot,
                    _build_statistics(),
                    _back_keyboard()
                )

            elif _dashboard_view == "home":
                text, buttons = _build_home()
                await _edit_dashboard(bot, text, buttons)

        except asyncio.CancelledError:
            break

        except Exception as exc:
            logger.warning("Auto refresh failed: %s", exc)


def register_handlers(bot: TelegramClient, forwarder=None):

    global _auto_refresh_task

    if _auto_refresh_task is None or _auto_refresh_task.done():
        _auto_refresh_task = asyncio.create_task(
            _auto_refresh(bot)
        )

    @bot.on(events.NewMessage(
        incoming=True,
        func=lambda e: e.is_private
    ))
    async def messages(event):

        if not _admin_only(event):
            return

        text = (event.raw_text or "").strip()

        if text.startswith("/start"):
            _user_states.pop(config.ADMIN_USER_ID, None)
            await _show_home(bot)

            try:
                await event.delete()
            except Exception:
                pass

            return

        state = _user_states.get(config.ADMIN_USER_ID)

        if not state:
            return

        try:
            if state == STATE_AWAIT_MSG:

                msg = event.message

                # Only text and Telegram stickers are accepted.
                is_sticker = bool(
                    msg.sticker
                )

                if msg.media and not is_sticker:
                    await _edit_dashboard(
                        bot,
                        "❌ Only text, emojis, Premium Custom Emojis "
                        "and Telegram stickers are supported.",
                        _back_keyboard()
                    )
                    return

                if is_sticker:
                    import os
                    import uuid

                    base = os.path.dirname(
                        os.path.abspath(config.DB_PATH)
                    )

                    media_dir = os.path.join(base, "media")
                    os.makedirs(media_dir, exist_ok=True)

                    ext = event.file.ext or ".webp"
                    path = os.path.join(
                        media_dir,
                        uuid.uuid4().hex + ext
                    )

                    saved = await bot.download_media(
                        msg,
                        file=path
                    )

                    if not saved:
                        raise RuntimeError("Sticker download failed")

                    db.save_message(
                        text="",
                        media_type="sticker",
                        file_path=str(saved)
                    )

                    result = "✅ Telegram sticker saved."

                elif msg.raw_text:
                    entities = []

                    from telethon.tl.types import MessageEntityCustomEmoji

                    for entity in msg.entities or []:
                        if isinstance(
                            entity,
                            MessageEntityCustomEmoji
                        ):
                            entities.append({
                                "type": "MessageEntityCustomEmoji",
                                "offset": entity.offset,
                                "length": entity.length,
                                "document_id": entity.document_id
                            })

                    db.save_message(
                        text=msg.raw_text,
                        media_type="text",
                        entities=entities
                    )

                    result = "✅ Text / Premium Emoji saved."

                else:
                    result = "❌ Unsupported content."

                _user_states.pop(config.ADMIN_USER_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _show_home(bot)
                return

            if state == STATE_AWAIT_GROUP_ADD:

                fwd = get_forwarder()

                if not fwd:
                    raise RuntimeError("Forwarder is not ready")

                member, entity = await fwd.check_membership(text)

                if not member or entity is None:
                    result = (
                        "❌ Your personal Telegram account "
                        "is not a member of this group."
                    )
                else:
                    from telethon.utils import get_peer_id

                    chat_id = str(get_peer_id(entity))
                    title = getattr(entity, "title", None) or text

                    if db.add_group(chat_id, title):
                        result = f"✅ Added: {title}"
                    else:
                        result = "⚠️ Group already exists."

                _user_states.pop(config.ADMIN_USER_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _edit_dashboard(
                    bot,
                    result,
                    _back_keyboard()
                )
                return

            if state == STATE_AWAIT_GLOBAL_INTERVAL:
                minutes = int(text)

                if minutes < 1:
                    raise ValueError

                db.set_setting(
                    "cycle_interval_minutes",
                    str(minutes)
                )

                _user_states.pop(config.ADMIN_USER_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _show_home(bot)
                return

            if state.startswith("group_interval:"):
                chat_id = state.split(":", 1)[1]
                minutes = int(text)

                if minutes < 1:
                    raise ValueError

                db.set_group_cycle_interval(chat_id, minutes)

                _user_states.pop(config.ADMIN_USER_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _show_home(bot)
                return

        except ValueError:
            await _edit_dashboard(
                bot,
                "❌ Please send a valid number greater than zero.",
                _back_keyboard()
            )

        except Exception:
            logger.exception("Dashboard input error")

            _user_states.pop(config.ADMIN_USER_ID, None)

            await _edit_dashboard(
                bot,
                "❌ Something went wrong. Please try again.",
                _back_keyboard()
            )

    @bot.on(events.CallbackQuery)
    async def callbacks(event):

        global _dashboard_view

        if not _admin_only(event):
            await event.answer("Not allowed", alert=True)
            return

        data = event.data.decode("utf-8")

        await event.answer()

        if data == "home":
            _user_states.pop(config.ADMIN_USER_ID, None)
            await _show_home(bot)

        elif data == "stats":
            _dashboard_view = "stats"

            await _edit_dashboard(
                bot,
                _build_statistics(),
                _back_keyboard()
            )

        elif data == "groups":
            _dashboard_view = "groups"

            await _edit_dashboard(
                bot,
                _build_groups(),
                _back_keyboard()
            )

        elif data == "set_msg":
            _dashboard_view = "input"
            _user_states[config.ADMIN_USER_ID] = STATE_AWAIT_MSG

            await _edit_dashboard(
                bot,
                "✉️ **SET BROADCAST MESSAGE**\n\n"
                "Send normal text, emojis, Premium Custom Emojis "
                "or a Telegram sticker.\n\n"
                "Photo, video and documents are disabled.\n\n"
                "Your next message will be saved.",
                _back_keyboard()
            )

        elif data == "preview":
            _dashboard_view = "preview"
            message = db.get_latest_message()

            if not message:
                preview = "No broadcast message saved."
            elif message.get("media_type") == "sticker":
                preview = (
                    "👁 **MESSAGE PREVIEW**\n\n"
                    "Type: Telegram Sticker\n"
                    "Status: Saved"
                )
            else:
                preview = (
                    "👁 **MESSAGE PREVIEW**\n\n"
                    f"{message.get('text') or 'Empty'}"
                )

            await _edit_dashboard(
                bot,
                preview,
                _back_keyboard()
            )

        elif data == "add_group":
            _dashboard_view = "input"
            _user_states[config.ADMIN_USER_ID] = STATE_AWAIT_GROUP_ADD

            await _edit_dashboard(
                bot,
                "➕ **ADD GROUP**\n\n"
                "Send group username or numeric Chat ID.\n\n"
                "Your personal Telegram account must be a member "
                "of the destination group.",
                _back_keyboard()
            )

        elif data == "rm_group":
            _dashboard_view = "remove"

            groups = db.get_all_groups()

            buttons = [
                [
                    Button.inline(
                        f"❌ {_short_name(g['title'] or g['chat_id'], 30)}",
                        f"del:{g['chat_id']}".encode()
                    )
                ]
                for g in groups
            ]

            buttons.append([
                Button.inline("⬅️ Back", b"home")
            ])

            await _edit_dashboard(
                bot,
                "➖ **REMOVE GROUP**\n\nSelect a group:",
                buttons
            )

        elif data.startswith("del:"):
            chat_id = data.split(":", 1)[1]
            db.remove_group(chat_id)

            await _edit_dashboard(
                bot,
                "✅ Group removed.",
                _back_keyboard()
            )

        elif data == "timing":
            _dashboard_view = "timing"

            groups = db.get_all_groups()

            buttons = [
                [
                    Button.inline(
                        f"⏱ {_short_name(g['title'] or g['chat_id'], 28)}",
                        f"gtime:{g['chat_id']}".encode()
                    )
                ]
                for g in groups
            ]

            buttons.append([
                Button.inline("🌐 Default Interval", b"globaltime")
            ])

            buttons.append([
                Button.inline("⬅️ Back", b"home")
            ])

            await _edit_dashboard(
                bot,
                "⏱ **TIMING SETTINGS**\n\n"
                "Choose a group to change its individual interval.",
                buttons
            )

        elif data == "globaltime":
            _dashboard_view = "input"
            _user_states[config.ADMIN_USER_ID] = STATE_AWAIT_GLOBAL_INTERVAL

            await _edit_dashboard(
                bot,
                "Send the default interval in minutes.\nExample: `17`",
                _back_keyboard()
            )

        elif data.startswith("gtime:"):
            chat_id = data.split(":", 1)[1]

            _dashboard_view = "input"
            _user_states[config.ADMIN_USER_ID] = (
                f"group_interval:{chat_id}"
            )

            await _edit_dashboard(
                bot,
                f"Send interval in minutes for `{chat_id}`.\n"
                "Example: `17`",
                _back_keyboard()
            )

        elif data == "toggle":
            fwd = get_forwarder()

            if not fwd:
                await event.answer("Forwarder not ready", alert=True)
                return

            if fwd.is_running:
                fwd.pause()
            else:
                if not db.get_latest_message():
                    await event.answer(
                        "Set a message first!",
                        alert=True
                    )
                    return

                fwd.start()

            await _show_home(bot)

        elif data == "flood":
            logs = db.get_recent_flood_logs(10)

            if not logs:
                text = "🌊 No FloodWait records."
            else:
                lines = ["🌊 **FLOOD LOGS**\n"]

                for item in logs:
                    lines.append(
                        f"Group: `{item['chat_id']}`\n"
                        f"Wait: `{item['wait_secs']} seconds`\n"
                    )

                text = "\n".join(lines)

            _dashboard_view = "flood"

            await _edit_dashboard(
                bot,
                text,
                _back_keyboard()
            )

        elif data == "refresh":
            if _dashboard_view == "stats":
                await _edit_dashboard(
                    bot,
                    _build_statistics(),
                    _back_keyboard()
                )
            else:
                await _show_home(bot)
