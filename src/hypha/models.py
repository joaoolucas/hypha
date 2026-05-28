"""Domain models shared across connectors, analysis and the bot.

Pydantic so reports serialize cleanly into the Redis cache and back.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── Raw chain objects ─────────────────────────────────────────────────────────
class TokenInfo(BaseModel):
    address: str                       # jetton master, normalized
    name: str = ""
    symbol: str = ""
    decimals: int = 9
    image: str | None = None
    total_supply: int = 0              # in smallest units
    mintable: bool = False
    admin_address: str | None = None   # None / zero == renounced
    holders_count: int = 0
    verification: str = "none"         # whitelist | blacklist | none

    @property
    def supply_float(self) -> float:
        return self.total_supply / (10 ** self.decimals)


class Holder(BaseModel):
    owner: str                         # owner wallet address
    wallet: str = ""                   # the jetton-wallet contract
    balance: int = 0                   # smallest units
    label: str | None = None           # from labeled_addresses registry
    is_excluded: bool = False          # pool / burn / locker -> not a real holder
    is_scam: bool = False


# ── Per-feature reports ───────────────────────────────────────────────────────
class HolderReport(BaseModel):
    holders_count: int = 0
    counted_holders: int = 0           # after excluding pools/burn/lockers
    top10_pct: float = 0.0             # % of circulating supply
    top20_pct: float = 0.0
    gini: float = 0.0
    dev_pct: float = 0.0               # admin/dev allocation %
    top1_pct: float = 0.0
    excluded_pct: float = 0.0          # supply in pools/burn/lockers
    top_holders: list[Holder] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LockStatus(str, Enum):
    BURNED = "burned"
    LOCKED = "locked"
    PARTIAL = "partial"
    UNLOCKED = "unlocked"
    NONE = "none"


class DexReport(BaseModel):
    has_pool: bool = False
    venues: list[str] = Field(default_factory=list)   # stonfi, dedust, ...
    liquidity_usd: float = 0.0
    market_cap_usd: float | None = None
    price_usd: float | None = None
    volume24h_usd: float | None = None
    lp_status: LockStatus = LockStatus.NONE
    liq_to_mcap_pct: float | None = None
    pools: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class LaunchStatus(str, Enum):
    ON_CURVE = "on_curve"
    GRADUATED = "graduated"
    LISTED = "listed"
    UNKNOWN = "unknown"


class LaunchpadReport(BaseModel):
    launchpad: str | None = None       # gaspump | blum | tonup | stonfi | ...
    is_known: bool = False
    status: LaunchStatus = LaunchStatus.UNKNOWN
    curve_progress_pct: float | None = None
    graduation_dex: str | None = None
    age_days: int | None = None
    notes: list[str] = Field(default_factory=list)


class WalletCluster(BaseModel):
    wallets: list[str]
    supply_pct: float
    reason: str                        # e.g. "common funder", "same-block buy"
    contains_dev: bool = False


class BundleReport(BaseModel):
    bundled_pct: float = 0.0
    largest_cluster_pct: float = 0.0
    cluster_count: int = 0
    dev_in_cluster: bool = False
    clusters: list[WalletCluster] = Field(default_factory=list)
    confidence: str = "limited"        # API-only depth
    notes: list[str] = Field(default_factory=list)


class PortfolioReport(BaseModel):
    common_tokens: list[dict] = Field(default_factory=list)  # {symbol, holders, address}
    notes: list[str] = Field(default_factory=list)


# ── Score ─────────────────────────────────────────────────────────────────────
class PillarScore(BaseModel):
    key: str
    label: str
    emoji: str
    score: float | None = None         # 0..100, None if data missing
    weight: float = 0.0
    notes: list[str] = Field(default_factory=list)


class HyphaScore(BaseModel):
    score: int = 0                     # 0..100, final (after poison caps)
    raw: float = 0.0
    tier: str = "Toxic"
    badge: str = "☠️"
    confidence: str = "limited"
    pillars: list[PillarScore] = Field(default_factory=list)
    poison_flags: list[str] = Field(default_factory=list)


# ── Aggregate ─────────────────────────────────────────────────────────────────
class TokenReport(BaseModel):
    token: TokenInfo
    holders: HolderReport | None = None
    dex: DexReport | None = None
    launchpad: LaunchpadReport | None = None
    bundle: BundleReport | None = None
    portfolio: PortfolioReport | None = None
    score: HyphaScore | None = None
    generated_at: float = 0.0          # epoch seconds; stamped by caller
    errors: list[str] = Field(default_factory=list)
