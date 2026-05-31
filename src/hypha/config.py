"""Central configuration. All tunables live here so we can calibrate without code changes."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ScoreWeights(BaseModel):
    """Pillar weights for the Hypha Score (must sum to 1.0). See SPEC.md §5."""

    distribution: float = 0.25
    bundling: float = 0.25
    liquidity: float = 0.20
    dev_authority: float = 0.20
    launch_config: float = 0.10


class ScoreConfig(BaseModel):
    """Breakpoints for the piecewise scoring curves. Mirrors SPEC.md §5.2–5.3."""

    weights: ScoreWeights = ScoreWeights()

    # Distribution
    top10_good_pct: float = 15.0      # <= -> 100
    top10_bad_pct: float = 65.0       # >= -> 0
    holders_full: int = 50_000        # holder count that scores 100 (log scale)
    gini_good: float = 0.60           # <= -> 100
    gini_bad: float = 0.95            # >= -> 0

    # Bundling
    bundle_good_pct: float = 5.0      # <= -> 100
    bundle_bad_pct: float = 50.0      # >= -> 0
    bundle_dev_penalty: float = 20.0
    bundle_bigcluster_penalty: float = 15.0
    bundle_bigcluster_pct: float = 20.0

    # Liquidity
    liq_depth_full_usd: float = 100_000.0   # >= -> 100 (log scale)
    liq_ratio_good_pct: float = 10.0        # liq/mcap >= -> 100
    liq_ratio_bad_pct: float = 1.0          # liq/mcap <= -> 0
    lock_scores: dict[str, float] = {
        "burned": 100.0, "locked": 85.0, "partial": 50.0, "unlocked": 10.0, "none": 0.0,
    }

    # Dev & authority
    dev_good_pct: float = 2.0         # <= -> 100
    dev_bad_pct: float = 25.0         # >= -> 0
    mintable_penalty: float = 50.0
    admin_not_renounced_penalty: float = 15.0
    metadata_mutable_penalty: float = 15.0

    # Launch & config base scores by status
    launch_on_curve_base: float = 45.0
    launch_graduated_base: float = 92.0
    launch_listed_base: float = 80.0
    launch_unknown_base: float = 60.0
    launch_age_bonus: float = 10.0
    launch_age_days: int = 30
    launch_known_bonus: float = 5.0
    launch_no_pool_penalty: float = 15.0

    # Poison-flag caps (final = min(raw, cap) when tripped)
    cap_no_liquidity: float = 15.0
    cap_unlocked_high_dev: float = 25.0
    cap_mintable_whale: float = 20.0
    cap_heavy_bundle: float = 30.0
    poison_min_liq_usd: float = 500.0
    poison_dev_pct: float = 30.0
    poison_whale_pct: float = 50.0
    poison_bundle_pct: float = 60.0

    # Tier thresholds (lower bound -> label)
    tiers: list[tuple[float, str, str]] = [
        (85, "Golden Chanterelle", "🌟🍄"),
        (70, "Healthy Cap", "🍄"),
        (55, "Young Sprout", "🌱"),
        (40, "Spotted Cap", "⚠️"),
        (20, "Moldy", "🟤"),
        (0, "Toxic", "☠️"),
    ]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Telegram
    bot_token: str = ""

    # Providers
    tonapi_key: str = ""
    tonapi_base: str = "https://tonapi.io"
    tonapi_min_interval: float = 0.12  # min seconds between TonAPI calls (~8/s, under the 10 RPS tier)
    toncenter_key: str = ""
    toncenter_base: str = "https://toncenter.com/api/v3"
    stonfi_base: str = "https://api.ston.fi"
    dedust_base: str = "https://api.dedust.io/v2"
    swapcoffee_base: str = "https://backend.swap.coffee"
    geckoterminal_base: str = "https://api.geckoterminal.com/api/v2"
    dexscreener_base: str = "https://api.dexscreener.com"

    # Referral
    stonfi_referral_address: str = ""
    stonfi_referral_percent: float = 0.1
    swapcoffee_referral_name: str = ""
    redirect_base: str = "https://hypha.link"

    # Infra
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = ""
    log_level: str = "INFO"
    analysis_ttl: int = 300
    user_rate_per_min: int = 8
    sentry_dsn: str = ""

    # Top-wallet holdings (Feature 3) — fan-out is gated, so keep these bounded.
    whales_scan_max: int = 10          # how many top holders to scan
    whale_usd_threshold: float = 5_000.0    # a single bag worth >= this == a "whale" position
    whales_top_shared: int = 8         # shared bags to surface
    whales_min_shared: int = 2         # token must be held by >= this many to count as "shared"
    whales_dust_usd: float = 1_000.0   # drop near-worthless shared bags (spam airdrops) below this
    whales_concurrency: int = 6        # cap concurrent portfolio calls to avoid 429s

    # ── Whale-tracker alerts channel (the pivot: push whale ops to a channel) ──
    alerts_channel_id: str = ""        # @handle or -100… numeric id the bot posts alerts to
    alerts_enabled: bool = True        # master switch for the token-centric trade poller
    admin_ids: str = ""                # comma/space-separated tg user ids allowed to /track

    buy_alert_ton: float = 100.0       # min BUY size (TON) — secondary; the primary gate is "is a whale"
    buy_alert_usd: float = 200.0       # fallback BUY floor (USD) when the TON price is unavailable
    sell_alert_usd: float = 10_000.0   # post a SELL only at/above this USD (big dumps)
    whale_portfolio_ton: float = 1000.0     # buyer is a whale 🐋 at/above this TON-valued portfolio
    whale_portfolio_usd: float = 1_900.0    # fallback (USD) when the TON price is unavailable
    max_mcap_usd: float = 10_000_000.0 # only alert on tokens at/below this market cap (small-cap focus)

    # Token-centric discovery (watch the hottest pools' trade feeds)
    hot_pools_max: int = 120           # how many hot pools to watch for trades
    new_pools_reserve: int = 50        # of those, always watch the freshest launches (not crowded out by volume)
    # DexScreener search terms to pull extra TON pairs Gecko misses (the Uranus launchpad DEX).
    # Uranus trades are decoded from the Meme contract's on-chain Buy/Sell events (parse_uranus_events).
    dexscreener_queries: str = "uranus"
    trades_poll_secs: int = 120        # trade-poll cycle interval (seconds); trades come from TonAPI
    discovery_poll_secs: int = 1_800   # how often the hot-pool set is refreshed (Gecko)
    trade_concurrency: int = 6         # cap concurrent TonAPI pool-event calls
    gecko_min_interval: float = 5.0    # min seconds between GeckoTerminal calls (discovery only now)

    # Wallet-centric follow (Phase 3: auto-promote recurring big buyers, track them everywhere)
    follow_enabled: bool = True        # follow promoted whales into cold (non-trending) tokens
    follow_poll_secs: int = 180        # followed-wallet poll interval (seconds)
    followed_max: int = 150            # cap on followed wallets (RPS bound)
    promote_min_buys: int = 3          # qualifying big buys before a wallet is auto-followed
    promote_window_secs: int = 604_800 # window for counting a wallet's qualifying buys (7d)
    alert_dedup_ttl: int = 86_400      # don't repost the same op within this window
    trade_max_age_secs: int = 900      # ignore trades older than this (avoids restart-backlog floods)

    score: ScoreConfig = Field(default_factory=ScoreConfig)

    @property
    def dexscreener_query_list(self) -> list[str]:
        return [q.strip() for q in self.dexscreener_queries.replace(",", " ").split() if q.strip()]

    @property
    def admin_id_set(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_ids.replace(",", " ").split():
            try:
                out.add(int(part))
            except ValueError:
                continue
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
