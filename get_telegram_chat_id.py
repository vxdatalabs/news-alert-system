#!/usr/bin/env python3
"""
One-time helper: run this AFTER you've created your bot with @BotFather
and sent it at least one message (e.g. "hi"), to find your chat_id.

Usage:
    python3 get_telegram_chat_id.py <BOT_TOKEN>
"""
from __future__ import annotations

import sys

import requests


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 get_telegram_chat_id.py <BOT_TOKEN>")
        sys.exit(1)

    token = sys.argv[1]
    resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("ok"):
        print("Telegram API error:", data)
        sys.exit(1)

    results = data.get("result", [])
    if not results:
        print(
            "No messages found yet. Open Telegram, find your bot, and send it "
            "any message (like 'hi'), then run this script again."
        )
        sys.exit(1)

    seen = set()
    for update in results:
        msg = update.get("message") or update.get("channel_post")
        if not msg:
            continue
        chat = msg["chat"]
        key = (chat["id"], chat.get("username") or chat.get("first_name", ""))
        if key in seen:
            continue
        seen.add(key)
        print(f"chat_id: {chat['id']}   (from: {chat.get('username') or chat.get('first_name')})")

    print("\nPut the chat_id above into .env as TELEGRAM_CHAT_ID=<that number>")


if __name__ == "__main__":
    main()
