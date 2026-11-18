"""
session_generator.py
Run this ONCE on your phone (Termux), PC, or any device that can receive
the Telegram OTP.  It prints the SESSION_STRING you paste into Railway.

Usage:
    pip install telethon python-dotenv
    python session_generator.py
"""

import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


async def generate() -> None:
    print("=" * 60)
    print("  Telegram SESSION_STRING Generator")
    print("=" * 60)
    print()

    api_id_raw = os.environ.get("API_ID") or input("Enter your API_ID   : ").strip()
    api_hash = os.environ.get("API_HASH") or input("Enter your API_HASH : ").strip()
    api_id = int(api_id_raw)

    print()
    print("A code will be sent to your Telegram account.")
    print("If 2FA is enabled you will be asked for your password.")
    print()

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()          # interactive: asks for phone + OTP + 2FA

    session_string = client.session.save()
    print()
    print("=" * 60)
    print("YOUR SESSION_STRING (copy everything between the lines):")
    print("-" * 60)
    print(session_string)
    print("-" * 60)
    print()
    print("Add this as the SESSION_STRING environment variable in Railway.")
    print("Never share this string with anyone.")
    print("=" * 60)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(generate())
