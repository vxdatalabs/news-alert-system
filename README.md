# Real-Time News Alert System

A small, always-on service that watches a list of stock tickers for fresh headlines and pushes them
to your phone. It polls the [Finnhub](https://finnhub.io) company-news API on a schedule that adapts
to the US market session, removes duplicates, and delivers batched digests to **Telegram** and,
optionally, **Discord**. It runs unattended as a `systemd` service on an Oracle Cloud VM.

*Headlines only, not investment advice.*

## Architecture

```
Finnhub /company-news  ->  poll loop (session-aware cadence)  ->  dedupe (persisted seen-ids)
                                                                      |
                                       CSV alert log  <---------------+--->  batched digest
                                                                                |         |
                                                                           Telegram     Discord (optional)
```

| File | Role |
|---|---|
| `news_loop.py` | Main loop: decides the session, sets the poll cadence and lookback window, sends alerts |
| `news_provider.py` | Finnhub client, per-symbol polling with throttling, persisted de-duplication |
| `telegram_notifier.py` / `discord_notifier.py` | Batched delivery with message chunking and rate-limit handling |
| `config.py` | Watchlist, session windows, poll intervals, and settings read from environment variables |
| `get_telegram_chat_id.py` | One-time helper to find your Telegram chat id |
| `deploy/` | Scripts and a `systemd` unit to deploy to a Linux VM |

## Design decisions

- **Session-aware polling.** Pre-market, regular and after-hours sessions are defined in US/Eastern
  time and each has its own poll interval. Outside trading hours (nights and weekends) the loop
  sleeps and checks every 10 minutes instead of spinning.
- **Self-correcting lookback window.** Each poll looks back over the real time elapsed since the last
  *successful* poll, plus a safety margin, rather than a fixed window. If a poll runs late or fails,
  the next one automatically covers the gap, so headlines published in between are not silently missed.
- **Persisted de-duplication.** Seen headline ids are saved per symbol (capped at 500) so a restart
  doesn't re-send what is still inside the lookback window.
- **Batched digests, not one message per headline.** An early version sent one message per item and
  hit Telegram's per-chat rate limit (HTTP 429) after a backlog catch-up, losing alerts. Alerts are now
  grouped into digests, chunked under each platform's message-length limit, spaced out, and retried
  once after a rate-limit response.
- **Throttled API use.** Calls are spaced to stay under Finnhub's free-tier limit of 60 per minute.
- **No secrets in code.** Keys and tokens are read from environment variables or a git-ignored `.env`.
  Deploys never copy `.env` to the server, so a rotated key on the VM is never overwritten.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in your own values
```

1. Get a free API key from Finnhub and put it in `.env`.
2. Create a Telegram bot with @BotFather, send it any message, then find your chat id:
   `python3 get_telegram_chat_id.py <BOT_TOKEN>`
3. Optional: add a Discord webhook URL for a second delivery channel.
4. Edit `WATCHLIST` in `config.py` (the list in the repo is only an example).

```bash
python3 news_loop.py --once   # one poll cycle, for testing
python3 news_loop.py          # run continuously (Ctrl-C to stop)
```

Alerts are also appended to `logs/news_alerts.csv`.

## Deploy to a Linux VM (Oracle Cloud)

`deploy/deploy.sh` copies the code to the VM, and `deploy/remote_setup.sh` installs dependencies,
checks timezone data, and installs and starts the `news-alert` `systemd` service
(`Restart=always`, logs to the journal).

```bash
VM_HOST=user@your.vm.ip SSH_KEY=~/path/to/your-key ./deploy/deploy.sh
# on the VM: put your .env in ~/news_alert_app/, then
journalctl -u news-alert -f
```

## Limitations and next steps

- One news source (Finnhub's free tier), headlines only, with no sentiment scoring or ranking.
- Single process with file-based state, which is fine for one user and one VM.
- Ideas: ticker-specific alert rules, headline relevance filtering, a health-check ping, and
  deploying through CI instead of a manual script.

## How it was built

I directed Claude through requirements, architecture and debugging, deployed it to Oracle Cloud,
and fixed the production issues that came up (missed headlines and Telegram rate limiting).

## License

MIT
