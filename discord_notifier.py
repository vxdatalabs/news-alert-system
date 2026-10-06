"""
Discord push notifications for new watchlist headlines, via an incoming
webhook (no bot hosting/gateway needed - just a URL we POST to).

Mirrors telegram_notifier.py's approach: batch all new headlines from one
poll cycle into as few messages as possible (chunked to stay under
Discord's 2000-char message limit), and respect Discord's webhook rate
limit (~30 requests/minute per webhook, enforced per-route with a
Retry-After header on 429).
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("discord_notifier")

MAX_MESSAGE_CHARS = 1900  # margin under Discord's 2000 hard limit
MIN_SECONDS_BETWEEN_MESSAGES = 0.5  # well under the ~30/min webhook limit


def _send_one(webhook_url: str, content: str, retried: bool = False) -> None:
    try:
        resp = requests.post(
            webhook_url,
            json={"content": content},
            timeout=10,
        )
        if resp.status_code == 429 and not retried:
            try:
                retry_after = resp.json().get("retry_after", 5)
            except ValueError:
                retry_after = 5
            log.warning("Discord rate-limited us, waiting %ss then retrying once", retry_after)
            time.sleep(retry_after + 1)
            _send_one(webhook_url, content, retried=True)
            return
        if not resp.ok:
            log.error("Discord send failed: %s %s", resp.status_code, resp.text[:200])
    except requests.RequestException as exc:
        log.error("Discord send failed: %s", exc)


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


def notify_batch(webhook_url: str, session: str, items: list) -> None:
    """
    Send every NewsItem in `items` (from one poll cycle) as one or a few
    digest messages to a Discord channel via webhook, instead of one
    message per item. `items` is a list of news_provider.NewsItem,
    newest-first.
    """
    if not webhook_url:
        log.error(
            "DISCORD_WEBHOOK_URL not set - can't send. See README.md for setup."
        )
        return
    if not items:
        return

    header = f"\U0001F4F0 **{len(items)} new headline(s) ({session})**"
    lines = []
    for item in items:
        lines.append(f"**{item.symbol}**: {item.headline} ({item.source}) {item.url}".strip())

    chunks = _chunk_messages(header, lines)
    for i, chunk in enumerate(chunks):
        _send_one(webhook_url, chunk)
        if i < len(chunks) - 1:
            time.sleep(MIN_SECONDS_BETWEEN_MESSAGES)
