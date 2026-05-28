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
    toncenter_key: str = ""
    toncenter_base: str = "https://toncenter.com/api/v3"
    stonfi_base: str = "https://api.ston.fi"
    dedust_base: str = "https://api.dedust.io/v2"
    swapcoffee_base: str = "https://backend.swap.coffee"
    geckoterminal_base: str = "https://api.geckoterminal.com/api/v2"

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

    score: ScoreConfig = Field(default_factory=ScoreConfig)


@lru_cache
def get_settings() -> Settings:
    return Settings()
