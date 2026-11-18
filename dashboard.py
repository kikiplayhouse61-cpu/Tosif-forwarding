import os
import uuid
import logging

from telethon import events, Button
from telethon.tl.types import (
    DocumentAttributeSticker,
    MessageEntityCustomEmoji
)

import database as db
from config import config

logger = logging.getLogger(__name__)

ADMIN_ID = config.ADMIN_USER_ID

_dashboard_ids = {}
_user_states = {}


def _media_directory():
    base = os.path.dirname(os.path.abspath(config.DB_PATH))
    path = os.path.join(base, "media")
    os.makedirs(path, exist_ok=True)
    return path


def _keyboard():
    return [
        [
            Button.inline("✉️ Set Message", b"setmsg"),
            Button.inline("📋 Message Preview", b"preview")
        ],
        [
            Button.inline("➕ Add Group", b"addgroup"),
            Button.inline("➖ Remove Group", b"removegroup")
        ],
        [
            Button.inline("👥 Groups", b"groups"),
            Button.inline("⏱ Timing", b"timing")
        ],
        [
            Button.inline("📊 Statistics", b"stats"),
            Button.inline("🌊 Flood Logs", b"flood")
        ],
        [
            Button.inline("▶️ Start", b"startfw"),
            Button.inline("⏸ Pause", b"pausefw")
        ],
        [
            Button.inline("🔄 Refresh", b"home")
        ]
    ]


def _back():
    return [[Button.inline("⬅️ Back", b"home")]]


def _status(forwarder):
    groups = db.get_all_groups()
    message = db.get_latest_message()

    running = forwarder.is_running if forwarder else False
    total = int(db.get_setting("total_sent", "0"))

    if message:
        kind = "Sticker" if message["media_type"] == "sticker" else "Text"
        preview = message.get("text") or "Sticker saved"
        preview = preview[:100]
    else:
        kind = "Not set"
        preview = "No broadcast message"

    current = forwarder.current_group if forwarder else None

    return (
        "✦ **HABIBI FORWARDER**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"Status: {'🟢 Running' if running else '🔴 Paused'}\n"
        f"Groups: `{len(groups)}`\n"
        f"Total successful sends: `{total}`\n"
        f"Content type: `{kind}`\n"
        f"Content: `{preview}`\n"
        f"Current group: `{current or 'Idle'}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Select an option below."
    )


async def _show(client, chat_id, text, buttons=None):
    message_id = _dashboard_ids.get(chat_id)

    if message_id:
        try:
            await client.edit_message(
                chat_id,
                message_id,
                text,
                buttons=buttons
            )
            return
        except Exception as exc:
            logger.debug("Dashboard edit failed: %s", exc)

    sent = await client.send_message(
        chat_id,
        text,
        buttons=buttons
    )
    _dashboard_ids[chat_id] = sent.id


async def _home(client, forwarder):
    await _show(
        client,
        ADMIN_ID,
        _status(forwarder),
        _keyboard()
    )


def _save_custom_emoji_entities(message):
    result = []

    for entity in message.entities or []:
        if isinstance(entity, MessageEntityCustomEmoji):
            result.append({
                "type": "MessageEntityCustomEmoji",
                "offset": entity.offset,
                "length": entity.length,
                "document_id": entity.document_id
            })

    return result


def register_handlers(bot, forwarder):

    @bot.on(events.NewMessage(
        incoming=True,
        func=lambda e: e.is_private
    ))
    async def private_messages(event):
        if event.sender_id != ADMIN_ID:
            return

        text = (event.raw_text or "").strip()

        if text.startswith("/start"):
            _user_states.pop(ADMIN_ID, None)
            await _home(bot, forwarder)
            try:
                await event.delete()
            except Exception:
                pass
            return

        state = _user_states.get(ADMIN_ID)

        if not state:
            return

        try:
            if state == "set_message":
                msg = event.message

                if msg.document:
                    is_sticker = any(
                        isinstance(attr, DocumentAttributeSticker)
                        for attr in (msg.document.attributes or [])
                    )
                else:
                    is_sticker = False

                if is_sticker:
                    ext = event.file.ext or ".webp"
                    filename = uuid.uuid4().hex + ext
                    destination = os.path.join(
                        _media_directory(), filename
                    )

                    saved_path = await bot.download_media(
                        msg,
                        file=destination
                    )

                    if not saved_path:
                        raise RuntimeError("Sticker download failed")

                    db.save_message(
                        text=msg.raw_text or "",
                        media_type="sticker",
                        file_path=str(saved_path),
                        entities=_save_custom_emoji_entities(msg)
                    )

                    result = "✅ Telegram sticker saved successfully."

                elif not msg.media and msg.raw_text:
                    db.save_message(
                        text=msg.raw_text,
                        media_type="text",
                        entities=_save_custom_emoji_entities(msg)
                    )

                    result = "✅ Text message saved successfully."

                else:
                    result = (
                        "❌ Only text, emojis, Premium Custom Emojis "
                        "and Telegram stickers are supported.\n"
                        "Photo, video and documents are not accepted."
                    )

                _user_states.pop(ADMIN_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _show(
                    bot,
                    ADMIN_ID,
                    result + "\n\n" + _status(forwarder),
                    _keyboard()
                )
                return

            if state == "add_group":
                if not text:
                    return

                member, entity = await forwarder.check_membership(text)

                if not member or entity is None:
                    result = (
                        "❌ Your personal Telegram account is not a "
                        "member of that group."
                    )
                else:
                    from telethon.utils import get_peer_id

                    chat_id = str(get_peer_id(entity))
                    title = getattr(entity, "title", None) or text

                    if db.add_group(chat_id, title):
                        result = f"✅ Group added: **{title}**"
                    else:
                        result = "⚠️ This group is already added."

                _user_states.pop(ADMIN_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _show(
                    bot, ADMIN_ID,
                    result + "\n\n" + _status(forwarder),
                    _keyboard()
                )
                return

            if state == "global_interval":
                minutes = int(text)

                if minutes < 1:
                    raise ValueError

                db.set_setting("cycle_interval_minutes", minutes)
                result = f"✅ Default interval set to {minutes} minutes."

                _user_states.pop(ADMIN_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _show(
                    bot, ADMIN_ID,
                    result + "\n\n" + _status(forwarder),
                    _keyboard()
                )
                return

            if state.startswith("group_interval:"):
                chat_id = state.split(":", 1)[1]
                minutes = int(text)

                if minutes < 1:
                    raise ValueError

                db.set_group_cycle_interval(chat_id, minutes)
                _user_states.pop(ADMIN_ID, None)

                try:
                    await event.delete()
                except Exception:
                    pass

                await _show(
                    bot,
                    ADMIN_ID,
                    f"✅ Group interval updated to {minutes} minutes.",
                    _keyboard()
                )
                return

        except ValueError:
            await _show(
                bot,
                ADMIN_ID,
                "❌ Enter a valid number greater than zero.",
                _back()
            )

        except Exception as exc:
            logger.exception("Input processing error: %s", exc)
            _user_states.pop(ADMIN_ID, None)

            await _show(
                bot,
                ADMIN_ID,
                "❌ Something went wrong while processing your input.",
                _keyboard()
            )

    @bot.on(events.CallbackQuery)
    async def callbacks(event):
        if event.sender_id != ADMIN_ID:
            await event.answer("Not allowed", alert=True)
            return

        data = event.data.decode("utf-8")
        await event.answer()

        if data == "home":
            _user_states.pop(ADMIN_ID, None)
            await _home(bot, forwarder)

        elif data == "setmsg":
            _user_states[ADMIN_ID] = "set_message"
            await _show(
                bot,
                ADMIN_ID,
                "✉️ **SET BROADCAST CONTENT**\n\n"
                "Send one of the following:\n"
                "• Normal text\n"
                "• Normal emojis\n"
                "• Telegram Premium Custom Emojis\n"
                "• Telegram sticker / Premium sticker\n\n"
                "Photo, video and documents are disabled.\n\n"
                "Your next message will become the broadcast content.",
                _back()
            )

        elif data == "preview":
            message = db.get_latest_message()

            if not message:
                text = "No broadcast message has been saved yet."
            elif message["media_type"] == "sticker":
                text = (
                    "📌 **CURRENT CONTENT PREVIEW**\n\n"
                    "Type: Telegram Sticker\n"
                    "Status: Saved\n"
                    "File: Available"
                )
            else:
                text = (
                    "📌 **CURRENT CONTENT PREVIEW**\n\n"
                    f"{message.get('text') or '(Empty)'}"
                )

            await _show(bot, ADMIN_ID, text, _back())

        elif data == "addgroup":
            _user_states[ADMIN_ID] = "add_group"
            await _show(
                bot,
                ADMIN_ID,
                "➕ **ADD GROUP**\n\n"
                "Send group username or numeric ID.\n\n"
                "Important: Your personal Telegram account must "
                "already be a member of the group.",
                _back()
            )

        elif data == "removegroup":
            groups = db.get_all_groups()

            if not groups:
                await _show(
                    bot, ADMIN_ID,
                    "No groups are currently added.",
                    _back()
                )
                return

            buttons = [
                [Button.inline(
                    f"❌ {g['title'] or g['chat_id']}"[:60],
                    f"del:{g['chat_id']}".encode()
                )]
                for g in groups
            ]
            buttons.append([Button.inline("⬅️ Back", b"home")])

            await _show(
                bot,
                ADMIN_ID,
                "Select the group you want to remove:",
                buttons
            )

        elif data.startswith("del:"):
            chat_id = data.split(":", 1)[1]
            db.remove_group(chat_id)

            await _show(
                bot,
                ADMIN_ID,
                "✅ Group removed.",
                _keyboard()
            )

        elif data == "groups":
            groups = db.get_all_groups()

            if not groups:
                text = "No groups added yet."
            else:
                lines = ["👥 **GROUP LIST**\n"]

                for index, group in enumerate(groups, 1):
                    interval = group["cycle_interval"] or int(
                        db.get_setting("cycle_interval_minutes", "17")
                    )

                    lines.append(
                        f"{index}. **{group['title'] or group['chat_id']}**\n"
                        f"ID: `{group['chat_id']}`\n"
                        f"Interval: `{interval} min`\n"
                    )

                text = "\n".join(lines)

            await _show(bot, ADMIN_ID, text, _back())

        elif data == "timing":
            groups = db.get_all_groups()

            buttons = [
                [Button.inline(
                    f"⏱ {g['title'] or g['chat_id']}"[:60],
                    f"gtime:{g['chat_id']}".encode()
                )]
                for g in groups
            ]

            buttons.append([
                Button.inline("🌐 Default Interval", b"globaltime")
            ])
            buttons.append([Button.inline("⬅️ Back", b"home")])

            await _show(
                bot,
                ADMIN_ID,
                "⏱ **TIMING SETTINGS**\n\n"
                "Choose a group to change its individual interval, "
                "or set the default interval.\n\n"
                "Minimum gap between different group sends: 60 seconds.",
                buttons
            )

        elif data == "globaltime":
            _user_states[ADMIN_ID] = "global_interval"
            await _show(
                bot,
                ADMIN_ID,
                "Send the default interval in minutes.\nExample: `17`",
                _back()
            )

        elif data.startswith("gtime:"):
            chat_id = data.split(":", 1)[1]
            _user_states[ADMIN_ID] = f"group_interval:{chat_id}"

            await _show(
                bot,
                ADMIN_ID,
                f"Send the interval in minutes for group `{chat_id}`.\n"
                "Example: `10`",
                _back()
            )

        elif data == "stats":
            stats = db.get_send_stats()

            await _show(
                bot,
                ADMIN_ID,
                "📊 **STATISTICS**\n\n"
                f"Total attempts: `{stats['total']}`\n"
                f"Successful: `{stats['success']}`\n"
                f"Failed: `{stats['failed']}`\n"
                f"Groups: `{len(db.get_all_groups())}`\n"
                f"Total successful sends: "
                f"`{db.get_setting('total_sent', '0')}`",
                _back()
            )

        elif data == "flood":
            logs = db.get_recent_flood_logs(10)

            if not logs:
                text = "No FloodWait records."
            else:
                lines = ["🌊 **RECENT FLOOD LOGS**\n"]

                for item in logs:
                    lines.append(
                        f"Group: `{item['chat_id']}`\n"
                        f"Wait: `{item['wait_secs']} seconds`\n"
                    )

                text = "\n".join(lines)

            await _show(bot, ADMIN_ID, text, _back())

        elif data == "startfw":
            forwarder.start()
            await _home(bot, forwarder)

        elif data == "pausefw":
            forwarder.pause()
            await _home(bot, forwarder)
