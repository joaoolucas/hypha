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
    dev_sold: bool | None = None       # admin/dev wallet has transferred tokens out
    top1_pct: float = 0.0
    excluded_pct: float = 0.0          # supply in pools/burn/lockers
    growth_delta: int | None = None    # holder count delta vs the most recent prior snapshot
    growth_secs: float | None = None   # seconds since that snapshot
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
    price_change_24h: float | None = None
    change_5m: float | None = None
    change_1h: float | None = None
    vol_trend: str | None = None        # "Rising 📈" | "Cooling 📉" | "Steady ➡️"
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


class TokenHolding(BaseModel):
    """A token held in common across the scanned top wallets."""

    address: str
    symbol: str = ""
    name: str = ""
    held_by: int = 0           # how many scanned top wallets hold it
    whales: int = 0            # how many hold it as a whale position
    total_usd: float = 0.0     # combined USD across those wallets
    verified: bool = False


class WhaleWallet(BaseModel):
    owner: str
    label: str | None = None
    portfolio_usd: float = 0.0
    stables_usd: float = 0.0     # USD held in stablecoins (USDT/USDe/…)
    tokens_usd: float = 0.0      # USD held in non-stable jettons
    token_count: int = 0
    top_bags: list[dict] = Field(default_factory=list)   # [{symbol, usd, whale}]


class PortfolioReport(BaseModel):
    scanned: int = 0
    whale_wallets: int = 0     # how many scanned top holders are whales (big multi-token bags)
    median_portfolio_usd: float = 0.0
    shared_tokens: list[TokenHolding] = Field(default_factory=list)
    wallets: list[WhaleWallet] = Field(default_factory=list)
    whale_usd: float = 0.0     # the USD threshold used to flag a bag as 🐋
    notes: list[str] = Field(default_factory=list)


# ── Whale-tracker (the alerts channel) ─────────────────────────────────────────
class HotPool(BaseModel):
    """A DEX pool we watch for big trades. Discovered from GeckoTerminal trending/new feeds."""

    pool_address: str
    token_address: str                 # the memecoin side (what a "buy" is buying)
    token_symbol: str = ""
    quote_symbol: str = ""             # the paired asset (TON / USDT / …)
    token_is_base: bool = True         # is the memecoin the pool's base token?
    venue: str = ""                    # stonfi | dedust | …
    reserve_usd: float = 0.0
    volume24h_usd: float = 0.0
    reason: str = ""                   # "trending" | "new"


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Trade(BaseModel):
    """A normalized DEX swap on a watched token — the raw event behind an alert."""

    side: TradeSide
    token_address: str                 # jetton master of the memecoin traded
    token_symbol: str = ""
    trader: str                        # raw `0:hex` address of the wallet that traded
    usd: float = 0.0                   # USD size of the trade (0 if unknown until enriched)
    ton_value: float = 0.0             # size of the trade in TON (the TON leg); 0 if not TON-paired
    token_amount: float = 0.0          # memecoin amount bought/sold
    price_usd: float | None = None
    venue: str = ""
    pool_address: str = ""
    tx_hash: str = ""
    ts: float = 0.0                    # epoch seconds (block time)
    source: str = "gecko"              # gecko | tonapi


class TraderContext(BaseModel):
    """Who the trader is — built lazily to tag an alert (🐋 whale / 👣 followed)."""

    address: str                       # raw form
    portfolio_usd: float = 0.0
    is_whale: bool = False             # portfolio clears the whale threshold
    is_followed: bool = False          # on our premium auto-followed list
    excluded: bool = False             # router / pool / burn — not a real trader
    label: str | None = None
    big_buys: int = 0                  # qualifying buys counted toward promotion
    top_bags: list[dict] = Field(default_factory=list)   # [{symbol, usd}]


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
