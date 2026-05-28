# Hypha 🍄 — TON Jetton Health Bot

> *Hypha are the threads that weave a mushroom's mycelium. This bot is the fruiting body; its mycelium threads through the TON chain — sensing how a token's supply, liquidity and wallets are really connected.*

A Telegram bot that analyzes the health and risk profile of **TON Jettons** (tokens) and
condenses everything into a single **Hypha Score 🍄**. Free to use; monetized through
context-aware referral "Buy" links.

---

## 1. Product overview

| # | Feature | One-liner |
|---|---------|-----------|
| 1 | **Holder Analysis** | Top 10/20 concentration, dev allocation, holder spread (Gini), decentralization verdict. |
| 2 | **Bundling Detection** | Cluster wallets likely controlled by one entity; reveal hidden concentration. |
| 3 | **Top Wallet Holdings** | What the biggest holders *also* own → narratives & project connections. |
| 4 | **DEX Payment / Liquidity Verification** | Pool exists + real depth + **LP locked/burned** + bonding-curve graduation completed. |
| 5 | **Hypha Score 🍄** | Proprietary 0–100 health score blending all signals into one mushroom tier. |
| 6 | **Launchpad & Bonding-Curve Detection** | Which launchpad minted it (GasPump / Blum / TonUP / …) and curve progress / graduation. |

**Decisions locked in**

- **Stack:** Python-first (`aiogram` bot + `arq` workers + `pandas`/`networkx` analytics).
- **Data layer:** API-only MVP (TonAPI + TON Center + DEX APIs + Redis cache), behind a
  connector abstraction so deep bundling can later move to a self-hosted indexer with no rewrite.
- **Monetization:** Free bot; every report carries a context-aware **Buy 🍄** button with our
  referral tag, plus a first-party redirect service for click attribution.

---

## 2. TON primer (why the design looks like it does)

- A token is a **Jetton** (TEP-74). Balances are **not** in one contract: each holder owns a
  personal **jetton-wallet** contract, and a **jetton master** holds metadata + total supply.
  "Get all holders" is therefore an *index* query — which is why we lean on indexed APIs.
- Addresses come raw (`0:hex`) and user-friendly (`EQ…` bounceable / `UQ…` non-bounceable).
  TonAPI accepts both; we normalize on input.
- **Launchpads** mint via a factory / shared code-hash. GasPump tokens are wrapped `$gasXXX`
  jettons that **graduate to DeDust** (and burn LP) around ~1,000 TON collected; Blum Memepad
  graduates to **STON.fi** at a 1,500 TON cap. This drives both Feature 6 and the buy-router.

---

## 3. Architecture

```
                 ┌─────────────────────────────┐
 Telegram  ◄────►│  aiogram bot (long-poll)     │   handlers · mushroom UI · keyboards
                 └───────────────┬──────────────┘
                                 │ heavy jobs → queue
                 ┌───────────────▼──────────────┐
                 │  arq workers                  │   holders · bundling · portfolios
                 │  pandas / networkx analytics  │   dex · launchpad · Hypha Score
                 └───────┬───────────────┬───────┘
        ┌────────────────┘               └──────────────┐
 ┌──────▼──────┐                          ┌──────────────▼─────────────┐
 │   Redis     │  cache + queue + quotas  │  Connectors (httpx)        │
 └─────────────┘                          │  TonAPI·TONCenter·STON.fi  │
 ┌─────────────┐                          │  DeDust·swap.coffee·Gecko  │
 │  Postgres   │  analyses · registries   └────────────────────────────┘
 │  users·clicks│
 └─────────────┘   ┌─────────────────────────────────────────────┐
                   │  FastAPI redirect svc  hypha.link/b/<id>     │  referral + click tracking
                   └─────────────────────────────────────────────┘
         all containers via Docker Compose on one NVMe VPS (≈4 vCPU / 8–16 GB)
```

**Connector abstraction.** Every external source sits behind a thin client (`connectors/`)
with retry + rate-limit handling. Feature code depends on an internal data-access interface,
never on a vendor — so "API → self-hosted indexer" is a swap, not a rewrite.

### Module map (`src/hypha/`)

```
config.py            pydantic-settings (keys, weights, referral addrs, TTLs)
models.py            domain dataclasses/pydantic (TokenInfo, Holder, *Report, HyphaScore)
cache.py             Redis JSON cache w/ in-memory fallback + @cached helper
connectors/          base.py · tonapi.py · toncenter.py · stonfi.py · dedust.py
                     swapcoffee.py · geckoterminal.py
analysis/            holders.py · bundling.py · portfolios.py · dex.py
                     launchpad.py · score.py · service.py (orchestrator)
referral/            router.py (status-aware buy-link builder) · registry.py
bot/                 main.py · ui.py · keyboards.py · handlers/
workers/             settings.py (arq) · tasks.py
web/                 redirect.py (FastAPI)
db/                  models.py · session.py
```

---

## 4. Data-source map

| Need | Primary | Fallback / extra |
|------|---------|------------------|
| Jetton info (supply, admin, mintable, metadata, holder count) | TonAPI `GET /v2/jettons/{addr}` | TON Center v3 `/jetton/masters` |
| Holder list + balances | TonAPI `GET /v2/jettons/{addr}/holders?limit=1000` | TON Center v3 `/jetton/wallets` |
| Account portfolio | TonAPI `GET /v2/accounts/{addr}/jettons` | — |
| Tx graph (bundling) | TonAPI `GET /v2/accounts/{addr}/events`, `/traces`, `GET /v2/traces/{id}` | self-hosted indexer (Phase B) |
| Pools / liquidity / LP | STON.fi `api.ston.fi/v1/pools*`, DeDust `api.dedust.io/v2/pools` | GeckoTerminal `/networks/ton/tokens/{addr}/pools` |
| Price / FDV / volume | GeckoTerminal `/networks/ton/tokens/{addr}` | DEX APIs |
| Best buy route + affiliate | swap.coffee `backend.swap.coffee` | STON.fi `referral_address` link |

**Auth:** TonAPI `Authorization: Bearer <key>` (no key ≈ 1 RPS); TON Center `X-API-Key`;
GeckoTerminal ~30 req/min unauth. All wrapped with caching + tenacity backoff.

**Holder-list cap:** indexed APIs cap ~1,000 holders. Sufficient for concentration/score;
exact long-tail counts need the self-hosted indexer later.

---

## 5. The Hypha Score 🍄 (formula)

A **0–100** score = weighted blend of five pillars, each scored 0–100, then clamped by
**poison flags**. Higher = healthier.

### 5.1 Pillars & weights

| Pillar | Weight | Measures |
|--------|:---:|----------|
| 🍄 **Distribution** | 25% | How spread the supply is across real holders. |
| 🕸️ **Bundling** | 25% | Hidden concentration via wallet clusters. |
| 💧 **Liquidity** | 20% | Depth + LP locked/burned + liq/mcap ratio. |
| 🔑 **Dev & Authority** | 20% | Dev allocation + mint/metadata authority risk. |
| 🌱 **Launch & Config** | 10% | Launchpad reputability, curve graduation, age, DEX config. |

`raw = Σ(weightᵢ · pillarᵢ)` over the pillars with available data (weights renormalized over
present pillars; missing data lowers **confidence**, see 5.4).

### 5.2 Pillar sub-formulas

Notation: `clamp(x)=max(0,min(100,x))`; shares in **percent**; balances exclude
known LP/burn/locker addresses (see §8 registry).

**🍄 Distribution**
```
top10  = 100 if t10 ≤ 15 ; 0 if t10 ≥ 65 ; else 100·(65 − t10)/50
holders= clamp(100 · log10(n+1) / log10(50000))          # 500→~57, 5k→~78, 50k→100
giniS  = 100 if g ≤ 0.60 ; 0 if g ≥ 0.95 ; else 100·(0.95 − g)/0.35
Distribution = 0.50·top10 + 0.30·holders + 0.20·giniS
```

**🕸️ Bundling**  (bp = % of supply in detected clusters; lc = largest cluster %)
```
base = 100 if bp ≤ 5 ; 0 if bp ≥ 50 ; else 100·(50 − bp)/45
Bundling = clamp(base − 20·[dev_in_cluster] − 15·[lc > 20])
```
Under API-only depth, bundling confidence = *limited* (window-based traces, not full graph).

**💧 Liquidity**  (liqUSD; ratio r = liquidity/marketcap in %)
```
lock  = 100 burned · 85 timelocked · 50 partial · 10 unlocked · 0 none
depth = clamp(100 · log10(liqUSD+1) / log10(100000))       # $5k→~46, $25k→~73, $100k→100
ratioS= 100 if r ≥ 10 ; 0 if r ≤ 1 ; else 100·(r − 1)/9
Liquidity = 0.45·lock + 0.40·depth + 0.15·ratioS
```

**🔑 Dev & Authority**  (da = dev/admin allocation %)
```
devS  = 100 if da ≤ 2 ; 0 if da ≥ 25 ; else 100·(25 − da)/23
auth  = clamp(100 − 50·[mintable] − 15·[admin_not_renounced] − 15·[metadata_mutable])
DevAuthority = 0.60·devS + 0.40·auth
```

**🌱 Launch & Config**
```
start by status:
  on_curve(not graduated)      → 45 + 0.20·curve_progress%        (early, unproven)
  graduated + LP burned        → 92
  listed on reputable DEX      → 80
  unknown / self-listed        → 60
+10 if age_days > 30 (survived) ; +5 if launchpad is reputable/known ; −15 if no DEX pool
LaunchConfig = clamp(start + bonuses)
```

### 5.3 Poison flags (hard caps)

Applied **after** the weighted sum — `final = min(raw, cap)` for each tripped flag:

| Flag condition | Cap |
|----------------|:---:|
| No sellable liquidity (no pool or liqUSD < $500) — honeypot risk | 15 |
| LP unlocked **and** dev allocation > 30% | 25 |
| Mintable **and** a single holder > 50% | 20 |
| Bundled supply > 60% | 30 |

### 5.4 Confidence

`confidence ∈ {high, medium, limited}` = function of how many pillars had full data and the
bundling depth used. Always shown — API-only bundling is explicitly flagged *limited*.

### 5.5 Mushroom tiers

| Score | Tier | Badge |
|------:|------|-------|
| 85–100 | **Golden Chanterelle** — prime | 🌟🍄 |
| 70–84 | **Healthy Cap** — strong | 🍄 |
| 55–69 | **Young Sprout** — fair | 🌱 |
| 40–54 | **Spotted Cap** — caution | ⚠️ |
| 20–39 | **Moldy** — high risk | 🟤 |
| 0–19 | **Toxic** — avoid | ☠️ |

### 5.6 Worked example

`t10=42%, holders=1,800, gini=0.88, bp=12%, dev_in_cluster=yes, lc=15%, liqUSD=$18k,`
`lock=burned, r=6%, da=4%, mintable=no, renounced=yes, status=graduated+LP burned, age=45d`

- Distribution: top10 `100·(65−42)/50=46`; holders `log10(1801)/log10(50000)·100≈69`; gini `100·(0.95−0.88)/0.35=20` → `0.5·46+0.3·69+0.2·20≈48`
- Bundling: base `100·(50−12)/45≈84` − 20 (dev) − 0 → `64`
- Liquidity: lock `100`; depth `log10(18001)/log10(100000)·100≈85`; ratio `100·(6−1)/9≈56` → `0.45·100+0.40·85+0.15·56≈87`
- Dev&Auth: devS `100·(25−4)/23≈91`; auth `100` → `0.6·91+0.4·100=95`
- Launch: `92 + 10(age) + 5(known) = 100 (clamped)`
- raw `= .25·48 + .25·64 + .20·87 + .20·95 + .10·100 = 12+16+17.4+19+10 = 74.4`
- No poison flags → **Hypha Score 74 → 🍄 Healthy Cap (strong)**, confidence *medium*
  (bundling limited under API-only).

> Weights, curve breakpoints and caps live in `config.py` (`ScoreConfig`) so we can calibrate
> against real tokens without code changes.

---

## 6. Referral / monetization

**Buy-router** picks the venue from Feature-6 status, then tags it:

| Token status | Venue | Referral mechanism |
|--------------|-------|--------------------|
| On bonding curve (GasPump) | GasPump | launchpad buy link |
| On bonding curve (Blum) | Blum Memepad | launchpad buy link |
| Graduated / listed | **swap.coffee** (aggregator, best price) | `referral_name` |
| STON.fi pool present | STON.fi | `app.ston.fi/swap?ft=TON&tt=<jetton>&referral_address=<addr>` |
| DeDust-only | swap.coffee or STON.fi | (DeDust has no referral URL — SDK-only) |

**Attribution.** Buy buttons point at our redirect service `hypha.link/b/<id>` → logs
`(user, token, venue, ts)` to Postgres → `302` to the tagged URL. Revenue reconciled against
each DEX's referral dashboard. (Raw deep-links are the fallback if the redirect svc is down.)

---

## 7. Bot UX (mushroom language)

**Commands**
```
/start            spore intro + how-to
/help             command list
/analyze <addr>   full report (also triggered by pasting a jetton address)
/score   <addr>   just the Hypha Score card
/holders <addr>   holder breakdown
/bundle  <addr>   bundling clusters
/whales  <addr>   top wallets' other holdings
/dex     <addr>   liquidity & LP verification
```

**Flow.** Paste address → instant "🍄 *sprouting analysis…*" placeholder → workers fan out →
message edited in place with the report card + **Buy 🍄** / **🔁 Refresh** / **🔬 Details** buttons.

**Copy system.** All user-facing strings + emoji live in `bot/ui.py` (mushroom theme: spores,
caps, mycelium, mold, toxic). One place to tune voice.

**Report card (sketch)**
```
🍄 HYPHA REPORT — $SHROOM
Healthy Cap · 74/100 · confidence: medium

🍄 Distribution   46  ▓▓▓▓▒▒▒▒▒▒
🕸️ Bundling       64  ▓▓▓▓▓▓▒▒▒▒
💧 Liquidity      87  ▓▓▓▓▓▓▓▓▒▒
🔑 Dev & Auth     95  ▓▓▓▓▓▓▓▓▓▒
🌱 Launch         100 ▓▓▓▓▓▓▓▓▓▓

Top10 42% · 1.8k holders · dev 4% · LP 🔥burned
Launchpad: GasPump → graduated (DeDust)
⚠️ dev wallet appears in a bundle cluster
[ Buy 🍄 ] [ 🔁 Refresh ] [ 🔬 Details ]
```

---

## 8. Data model & registries (Postgres)

- `tokens` — cached jetton info + metadata (TTL refresh).
- `analyses` — last computed report per token (score history rows).
- `users` — tg user, quotas, referral attribution.
- `clicks` — redirect-svc events (user, token, venue, ts).
- `labeled_addresses` — **the moat**: burn (`UQAAAA…AJKZ`), STON.fi routers/pool wallets,
  DeDust vaults/pools, liquidity lockers, CEX deposits, known bundlers. Seeded + curated.
- `launchpad_signatures` — factory addresses / code-hashes per launchpad for Feature 6.

Holder analysis & bundling **exclude** `labeled_addresses` of type pool/burn/locker so
concentration reflects real holders, not liquidity.

---

## 9. Infra & ops

- **One VPS**, Docker Compose: `bot`, `worker` (arq), `redis`, `postgres`, `web` (redirect).
- **Caching/quotas** in Redis: per-token analysis TTL (minutes); per-user rate limits (each
  `/analyze` fans out many calls — protects API bill + abuse).
- **Secrets** via env (`.env`); `.env.example` documents every key.
- **Observability:** structlog JSON logs; Sentry for errors; uptime monitor (external APIs flake).
- **CI/CD:** push to `main` → build image → deploy (per repo convention).
- **Scale path:** add a dedicated indexer box (`ton-index-worker` + Postgres) and flip the
  bundling connector from trace-API to indexed-SQL — feature code unchanged.

---

## 10. Roadmap

- **Phase 0 — Skeleton:** compose stack, config, bot echo, connector stubs, UI system. *(this commit)*
- **Phase 1 — Holders + Hypha Score v1:** the hero loop, end-to-end with TonAPI. *(this commit)*
- **Phase 2 — Launchpad + curve + DEX/LP verification:** feeds score + buy-router.
- **Phase 3 — Bundling (trace-API depth):** networkx funding-graph clusters.
- **Phase 4 — Top-wallet holdings + redirect svc + click analytics.**
- **Phase 5 — Calibration:** labeled-address registry, score-weight tuning, quota hardening.

---

## 11. Limitations (honest)

- Holder list capped ~1k (API-only); long tail approximate until self-hosted indexer.
- Bundling under API-only is window/trace-based → confidence *limited*; deep graph needs Phase B.
- Referral terms per DEX change — verify before each launch; DeDust referral is SDK-only.
- Score is a heuristic risk aid, **not** financial advice. The bot says so.
