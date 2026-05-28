# Hypha 🍄

A Telegram bot that scores the health & risk of **TON Jettons** — holder distribution,
bundling, liquidity, dev/authority and launchpad status — into one **Hypha Score**.

See [`SPEC.md`](./SPEC.md) for the full design and the Hypha Score formula.

## Quick start (local)

```bash
cp .env.example .env          # fill in BOT_TOKEN and TONAPI_KEY (minimum)
docker compose up --build     # bot + worker + redis + postgres + redirect svc
```

Or run just the bot against the public API tier (no key, ~1 RPS):

```bash
pip install -e .              # Python 3.11+
export BOT_TOKEN=...          # from @BotFather
python -m hypha.bot.main
```

Then DM the bot: `/analyze <jetton-address>` (or just paste an `EQ…` / `UQ…` address).

## Status

- ✅ Phase 0 — skeleton (compose, config, bot, connectors, UI)
- ✅ Phase 1 — holder analysis + Hypha Score v1 (TonAPI)
- 🔜 Phase 2 — launchpad / bonding-curve / DEX-LP verification
- 🔜 Phase 3 — bundling clusters (trace API)
- 🔜 Phase 4 — top-wallet holdings + referral redirect + click analytics

## Layout

```
src/hypha/
  config.py    connectors/   analysis/   referral/   bot/   workers/   web/   db/
```

> Hypha is a heuristic risk aid, not financial advice.
