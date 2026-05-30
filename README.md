# Hypha 🍄

Two products, one mycelium on the **TON** chain:

1. **Whale-tracker channel** — watches the hottest TON pools (and a self-built list of
   followed wallets) and pushes alerts to a Telegram channel: *"🐋 whale bought $4.2k of
   $SHROOM"*, each carrying the token's **Hypha Score** + the buyer's portfolio context.
2. **On-demand analysis bot** — paste a jetton address, get its **Hypha Score** (holder
   distribution, liquidity, dev/authority, launchpad).

See [`SPEC.md`](./SPEC.md) for the Hypha Score formula.

## How the tracker works

```
GeckoTerminal trending + new pools  →  per-pool TRADE FEED  →  classify buy/sell ≥ threshold
   →  enrich buyer (🐋 portfolio? 👣 followed?) + Hypha Score  →  post to channel
Recurring big buyers are auto-promoted to a followed list and tracked into cold tokens
(TonAPI account events), so early accumulation surfaces before a token trends.
```

Token-centric by design: instead of polling a huge wallet list, we watch where the action
is and catch *any* big buyer in the feed. The followed list bootstraps itself from there.

## Quick start (local)

```bash
cp .env.example .env          # set BOT_TOKEN, TONAPI_KEY, ALERTS_CHANNEL_ID
docker compose up --build     # bot + tracker + worker + redis + postgres + redirect svc
```

Set up the channel: create a Telegram channel, add the bot as an **admin** (post rights),
and put its `@handle` or `-100…` id in `ALERTS_CHANNEL_ID`. Tune `BUY_ALERT_USD` /
`SELL_ALERT_USD` / `HOT_POOLS_MAX` / poll intervals in `.env`.

Run a single piece directly (Python 3.11+, `pip install -e .`):

```bash
python -m hypha.tracker.main   # the whale-tracker poller (posts to the channel)
python -m hypha.bot.main       # the on-demand analysis bot + /track admin commands
```

Bot commands: paste any `EQ…`/`UQ…` address for a report; `/track <wallet>`, `/untrack`,
`/followed` (admin, gated by `ADMIN_IDS`) manage the followed list.

## Status

- ✅ On-demand analysis bot + Hypha Score v1 (TonAPI)
- ✅ Whale-tracker channel — token-centric trade detection + Hypha-enriched alerts
- ✅ Auto-promotion — recurring big buyers followed into cold tokens
- ✅ Alert log (Postgres) — substrate for win-rate calibration
- 🔜 Win-rate scoring cron (did the token run after the whale bought?) + SSE near-real-time feed

## Layout

```
src/hypha/
  config.py   connectors/   analysis/   tracker/   referral/   bot/   workers/   web/   db/
                  ▲ geckoterminal: trending/new pools + pool trades
            analysis/discovery.py · analysis/trades.py   (pure: hot-pool + swap classification)
            tracker/{service,enrich,state,main}.py        (loops, enrichment, cursors/dedup)
            bot/channel.py                                (alert rendering + publishing)
```

> Hypha is a heuristic risk aid, not financial advice.
