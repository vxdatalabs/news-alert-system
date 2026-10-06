"""
Config for the watchlist news-alert app.

Watchlist tickers, session windows (US/Eastern, matches how the market
actually trades regardless of the server's local timezone), and poll cadence
per session.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
WATCHLIST = [  # example list - replace with your own tickers
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL",
    "META", "TSLA", "AMD", "SPY", "QQQ",
]

# ---------------------------------------------------------------------------
# Session windows, US/Eastern (America/New_York), 24h "HH:MM"
# ---------------------------------------------------------------------------
SESSIONS = {
    "premarket": {"start": "04:00", "end": "09:30"},
    "regular":   {"start": "09:30", "end": "16:00"},
    "afterhours": {"start": "16:00", "end": "20:00"},
}

# Poll interval (seconds) per session. Outside all windows (overnight /
# weekend) the loop sleeps on CLOSED_POLL_SECONDS instead of spinning.
POLL_SECONDS = {
    "premarket": 60,
    "regular": 90,
    "afterhours": 90,
}
CLOSED_POLL_SECONDS = 600  # check every 10 min whether a session has opened

# ---------------------------------------------------------------------------
# Finnhub
# ---------------------------------------------------------------------------
DEFAULT_ENV_FILE = os.path.expanduser("~/news_alert_app/.env")


def _load_env_file(env_file: str) -> None:
    """Minimal KEY=VALUE .env loader (no extra dependency)."""
    path = Path(env_file)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file(os.environ.get("NEWS_ALERT_ENV_FILE", DEFAULT_ENV_FILE))
# Also check for a .env sitting right next to this file (when run from the
# project directory directly, which is the normal case).
_load_env_file(str(Path(__file__).resolve().parent / ".env"))

FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# ---------------------------------------------------------------------------
# Telegram (phone push alerts)
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# Discord (webhook push alerts - second delivery channel alongside Telegram)
# ---------------------------------------------------------------------------
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# How far back (minutes) to look on each poll for "new" news, as a safety
# margin on top of the dedupe-by-id logic (covers the very first poll after
# a session opens).
LOOKBACK_MINUTES_FIRST_POLL = 180

# ---------------------------------------------------------------------------
# Logging / state
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).resolve().parent / "logs"
ALERTS_CSV = LOG_DIR / "news_alerts.csv"
SEEN_IDS_FILE = LOG_DIR / "seen_ids.json"
