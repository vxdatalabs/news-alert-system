#!/usr/bin/env python3
"""
Watchlist news-alert loop.

Polls Finnhub for fresh headlines on every ticker in config.WATCHLIST,
at a cadence that adapts to which session we're in (premarket / regular
/ after-hours, all US/Eastern), and pushes new headlines to Telegram AND Discord as a batched digest
per poll cycle (not one message per headline - see telegram_notifier.py
/ discord_notifier.py for why). Discord delivery is optional: if
DISCORD_WEBHOOK_URL isn't set in .env, only Telegram fires.

The lookback window is dynamic: it always covers the actual elapsed
time since the last successful poll (plus a safety margin), rather
than assuming a fixed "3 minutes is enough". This makes coverage
self-correcting - if a poll ever runs late (slow network, a VM hiccup,
whatever), the next one automatically looks back far enough to close
the gap instead of silently missing whatever published during it.

Run it locally (or as a systemd service, see deploy/):

    python3 news_loop.py          # run continuously
    python3 news_loop.py --once   # single poll cycle, for testing

Stop with Ctrl-C.
"""
from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config
from news_provider import FinnhubNewsProvider, SeenIdStore, poll_watchlist
from telegram_notifier import notify_batch
from discord_notifier import notify_batch as discord_notify_batch

ET = ZoneInfo("America/New_York")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("news_loop")

# Safety margin added on top of the actual measured gap since the last
# poll, to absorb small clock/scheduling jitter.
LOOKBACK_SAFETY_MARGIN_MINUTES = 2
# Upper bound so a very long outage (VM down for days) doesn't try to
# backfill an unbounded window in one go.
MAX_LOOKBACK_MINUTES = 24 * 60


def _parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.split(":")
    return int(h), int(m)


def current_session(now_et: datetime) -> str | None:
    """Return 'premarket' | 'regular' | 'afterhours' | None (closed)."""
    if now_et.weekday() >= 5:  # Sat/Sun
        return None
    t = now_et.time()
    for name, window in config.SESSIONS.items():
        start_h, start_m = _parse_hhmm(window["start"])
        end_h, end_m = _parse_hhmm(window["end"])
        start = now_et.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        end = now_et.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        if start.time() <= t < end.time():
            return name
    return None


def log_alert(row: dict) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not config.ALERTS_CSV.exists()
    with config.ALERTS_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["symbol", "news_id", "headline", "source", "url", "published_at"]
        )
        if is_new:
            writer.writeheader()
        writer.writerow(row)


def run(once: bool = False) -> None:
    if not config.WATCHLIST:
        log.error("config.WATCHLIST is empty - nothing to poll.")
        sys.exit(1)

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.error(
            "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set in .env - "
            "see README.md for setup. Nothing will be delivered until "
            "these are set."
        )
        sys.exit(1)

    if not config.DISCORD_WEBHOOK_URL:
        log.warning(
            "DISCORD_WEBHOOK_URL not set in .env - Discord delivery will be "
            "skipped, Telegram will still work."
        )

    provider = FinnhubNewsProvider(config.FINNHUB_API_KEY)
    seen = SeenIdStore(config.SEEN_IDS_FILE)

    log.info(
        "Watching %d tickers: %s",
        len(config.WATCHLIST),
        ", ".join(config.WATCHLIST),
    )

    last_poll_finished_at: datetime | None = None

    while True:
        now_et = datetime.now(ET)
        session = current_session(now_et)

        if session is None:
            log.info(
                "Market closed (%s ET) - sleeping %ds",
                now_et.strftime("%a %H:%M"),
                config.CLOSED_POLL_SECONDS,
            )
            if once:
                return
            time.sleep(config.CLOSED_POLL_SECONDS)
            continue

        poll_started_at = datetime.now(timezone.utc)
        if last_poll_finished_at is None:
            lookback = config.LOOKBACK_MINUTES_FIRST_POLL
        else:
            elapsed_minutes = (
                poll_started_at - last_poll_finished_at
            ).total_seconds() / 60
            lookback = min(
                MAX_LOOKBACK_MINUTES,
                max(3, elapsed_minutes + LOOKBACK_SAFETY_MARGIN_MINUTES),
            )

        log.info(
            "[%s] polling %d tickers (lookback %.1fm)...",
            session,
            len(config.WATCHLIST),
            lookback,
        )

        try:
            new_items = poll_watchlist(provider, seen, config.WATCHLIST, lookback)
        except Exception:
            log.exception("Poll failed, will retry next cycle")
            new_items = []
        else:
            # Only advance the watermark on a successful poll, so a
            # failed cycle's gap gets covered by the next attempt too.
            last_poll_finished_at = datetime.now(timezone.utc)

        for item in new_items:
            log.info("NEW: [%s] %s (%s)", item.symbol, item.headline, item.source)
            log_alert(item.to_row())

        if new_items:
            try:
                notify_batch(
                    config.TELEGRAM_BOT_TOKEN,
                    config.TELEGRAM_CHAT_ID,
                    session,
                    new_items,
                )
            except Exception:
                log.exception("Telegram batch send failed, will continue polling")

            if config.DISCORD_WEBHOOK_URL:
                try:
                    discord_notify_batch(
                        config.DISCORD_WEBHOOK_URL,
                        session,
                        new_items,
                    )
                except Exception:
                    log.exception("Discord batch send failed, will continue polling")

        if once:
            return
        time.sleep(config.POLL_SECONDS[session])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watchlist news-alert loop")
    parser.add_argument(
        "--once", action="store_true", help="Run a single poll cycle and exit (for testing)"
    )
    args = parser.parse_args()
    try:
        run(once=args.once)
    except KeyboardInterrupt:
        log.info("Stopped.")
