"""
Finnhub-backed news provider for the watchlist news-alert app.

Uses Finnhub's free /company-news endpoint (per-symbol headlines) since
Webull's OpenAPI has no news endpoint. Free tier: 60 calls/min, which is
comfortably enough to poll ~30-40 tickers every 60-90s.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests

import config

log = logging.getLogger("news_provider")

FINNHUB_BASE = "https://finnhub.io/api/v1"


@dataclass
class NewsItem:
    symbol: str
    news_id: str
    headline: str
    summary: str
    source: str
    url: str
    published_at: datetime  # UTC

    def to_row(self) -> dict:
        return {
            "symbol": self.symbol,
            "news_id": self.news_id,
            "headline": self.headline,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
        }


class FinnhubError(RuntimeError):
    pass


class SeenIdStore:
    """
    Tracks which news ids we've already alerted on, per symbol, so a
    poll never re-notifies the same headline. Persisted to disk so a
    restart doesn't re-fire everything still inside the lookback window.
    """

    def __init__(self, path: Path):
        self.path = path
        self._seen: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._seen = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                log.warning("seen_ids file unreadable, starting fresh: %s", self.path)
                self._seen = {}

    def is_seen(self, symbol: str, news_id: str) -> bool:
        return news_id in self._seen.get(symbol, [])

    def mark_seen(self, symbol: str, news_id: str) -> None:
        ids = self._seen.setdefault(symbol, [])
        if news_id not in ids:
            ids.append(news_id)
        # Cap memory per symbol so this file doesn't grow forever.
        if len(ids) > 500:
            self._seen[symbol] = ids[-500:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._seen))


class FinnhubNewsProvider:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        if not api_key:
            raise FinnhubError(
                "FINNHUB_API_KEY is not set. Put it in news_alert_app/.env "
                "as FINNHUB_API_KEY=your_key_here."
            )
        self.api_key = api_key
        self.session = session or requests.Session()

    def fetch_company_news(
        self, symbol: str, from_dt: datetime, to_dt: datetime
    ) -> list[NewsItem]:
        """
        Fetch Finnhub company news for `symbol` between from_dt and to_dt
        (both UTC datetimes). Returns newest-first is NOT guaranteed by
        the API, so caller should not assume order.
        """
        params = {
            "symbol": symbol,
            "from": from_dt.strftime("%Y-%m-%d"),
            "to": to_dt.strftime("%Y-%m-%d"),
            "token": self.api_key,
        }
        resp = self.session.get(
            f"{FINNHUB_BASE}/company-news", params=params, timeout=15
        )
        if resp.status_code == 429:
            raise FinnhubError(f"Rate limited by Finnhub for {symbol} (429)")
        if not resp.ok:
            raise FinnhubError(
                f"Finnhub error for {symbol}: {resp.status_code} {resp.text[:200]}"
            )
        raw = resp.json()
        items: list[NewsItem] = []
        for entry in raw:
            try:
                published = datetime.fromtimestamp(
                    entry["datetime"], tz=timezone.utc
                )
            except (KeyError, TypeError, ValueError):
                continue
            if not (from_dt <= published <= to_dt):
                continue
            items.append(
                NewsItem(
                    symbol=symbol,
                    news_id=str(entry.get("id", entry.get("url", entry.get("headline")))),
                    headline=entry.get("headline", "(no headline)"),
                    summary=entry.get("summary", ""),
                    source=entry.get("source", ""),
                    url=entry.get("url", ""),
                    published_at=published,
                )
            )
        return items


def poll_watchlist(
    provider: FinnhubNewsProvider,
    seen: SeenIdStore,
    watchlist: Iterable[str],
    lookback_minutes: int,
    sleep_between_calls: float = 1.1,
) -> list[NewsItem]:
    """
    Poll every symbol in `watchlist` for news published within the last
    `lookback_minutes`, filter out anything already seen, mark the rest
    seen, and return only the genuinely new items (any symbol, any order).
    `sleep_between_calls` throttles our own request rate to stay well
    under Finnhub's free-tier 60/min limit.
    """
    now = datetime.now(timezone.utc)
    from_dt = now - timedelta(minutes=lookback_minutes)
    new_items: list[NewsItem] = []

    for symbol in watchlist:
        try:
            items = provider.fetch_company_news(symbol, from_dt, now)
        except FinnhubError as exc:
            log.warning("Skipping %s this poll: %s", symbol, exc)
            time.sleep(sleep_between_calls)
            continue

        for item in items:
            if seen.is_seen(symbol, item.news_id):
                continue
            seen.mark_seen(symbol, item.news_id)
            new_items.append(item)

        time.sleep(sleep_between_calls)

    seen.save()
    # Newest first for display/notification ordering.
    new_items.sort(key=lambda i: i.published_at, reverse=True)
    return new_items
