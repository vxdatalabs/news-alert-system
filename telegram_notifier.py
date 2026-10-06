"""
Telegram push notifications for new watchlist headlines.

Sends alerts via the Telegram Bot API. Batches all new headlines from
one poll cycle into as few messages as possible (chunked to stay under
Telegram's 4096-char message limit), rather than one message per
headline - this is both better UX (no flood of pings) and necessary to
stay under Telegram's ~1 message/second-per-chat rate limit, which a
one-message-per-item approach blew through badly after a backlog catch
-up (dozens of 429 "Too Many Requests" errors, with those failed sends
silently lost since nothing retried them).
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("telegram_notifier")

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 3500  # margin under Telegram's 4096 hard limit
MIN_SECONDS_BETWEEN_MESSAGES = 1.1  # Telegram allows ~1 msg/sec to one chat


def _escape_markdown_v2(text: str) -> str:
    """Escape the characters Telegram's MarkdownV2 parse mode requires."""
    specials = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in specials else c for c in text)


def _send_one(bot_token: str, chat_id: str, text: str, retried: bool = False) -> None:
    try:
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        if resp.status_code == 429 and not retried:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
            log.warning("Telegram rate-limited us, waiting %ss then retrying once", retry_after)
            time.sleep(retry_after + 1)
            _send_one(bot_token, chat_id, text, retried=True)
            return
        if not resp.ok:
            log.error("Telegram send failed: %s %s", resp.status_code, resp.text[:200])
    except requests.RequestException as exc:
        log.error("Telegram send failed: %s", exc)


def _chunk_messages(header: str, lines: list[str]) -> list[str]:
    """Pack `lines` into as few messages as possible under MAX_MESSAGE_CHARS."""
    chunks: list[str] = []
    current = header
    for line in lines:
        candidate = current + "\n" + line
        if len(candidate) > MAX_MESSAGE_CHARS and current != header:
            chunks.append(current)
            current = header + "\n" + line
        else:
            current = candidate
    if current != header:
        chunks.append(current)
    return chunks or [header]


def notify(
    bot_token: str,
    chat_id: str,
    title: str,
    subtitle: str,
    message: str,
    url: str = "",
) -> None:
    """Send a single alert. Kept for one-off/manual use; news_loop.py's
    normal path is notify_batch() below."""
    if not bot_token or not chat_id:
        log.error(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - can't send. "
            "See README.md for setup."
        )
        return
    lines = [f"*{_escape_markdown_v2(title)}*"]
    if subtitle:
        lines.append(_escape_markdown_v2(subtitle))
    lines.append(_escape_markdown_v2(message))
    if url:
        lines.append(_escape_markdown_v2(url))
    _send_one(bot_token, chat_id, "\n".join(lines))


def notify_batch(bot_token: str, chat_id: str, session: str, items: list) -> None:
    """
    Send every NewsItem in `items` (from one poll cycle) as one or a
    few digest messages, instead of one message per item. `items` is a
    list of news_provider.NewsItem, newest-first.
    """
    if not bot_token or not chat_id:
        log.error(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - can't send. "
            "See README.md for setup."
        )
        return
    if not items:
        return

    header = _escape_markdown_v2(f"\U0001F4F0 {len(items)} new headline(s) ({session})")
    lines = []
    for item in items:
        symbol = _escape_markdown_v2(item.symbol)
        headline = _escape_markdown_v2(item.headline)
        source = _escape_markdown_v2(item.source or "")
        lines.append(f"*{symbol}*: {headline} \\({source}\\)")

    chunks = _chunk_messages(header, lines)
    for i, chunk in enumerate(chunks):
        _send_one(bot_token, chat_id, chunk)
        if i < len(chunks) - 1:
            time.sleep(MIN_SECONDS_BETWEEN_MESSAGES)
